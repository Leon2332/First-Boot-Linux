package catalog

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"unicode/utf8"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
)

type Official struct {
	SchemaVersion int      `json:"schema_version"`
	Updated       string   `json:"updated"`
	Distros       []Distro `json:"distros"`
}

type Distro struct {
	ID                string    `json:"id"`
	Name              string    `json:"name"`
	Version           string    `json:"version"`
	Tagline           string    `json:"tagline"`
	Description       string    `json:"description"`
	Family            string    `json:"family"`
	Install           *string   `json:"install"`
	CanStage          bool      `json:"can_stage"`
	SuggestedDefault  bool      `json:"suggested_default"`
	Editions          []Edition `json:"editions"`
}

type Edition struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Default   bool    `json:"default"`
	Filename  string  `json:"filename"`
	URL       *string `json:"url"`
	SHA256    *string `json:"sha256"`
	SizeBytes *int64  `json:"size_bytes"`
}

type Shop struct {
	SchemaVersion int          `json:"schema_version"`
	Recommended   []ShopDistro `json:"recommended"`
	Catalog       []ShopDistro `json:"catalog"`
}

type ShopDistro struct {
	ID          string        `json:"id"`
	Name        string        `json:"name"`
	Version     string        `json:"version"`
	Tagline     string        `json:"tagline"`
	Description string        `json:"description"`
	Family      string        `json:"family"`
	Install     string        `json:"install"`
	Editions    []ShopEdition `json:"editions"`
}

type ShopEdition struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Default   bool   `json:"default"`
	Local     bool   `json:"local"`
	File      string `json:"file,omitempty"`
	URL       string `json:"url,omitempty"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
}

type Retailer struct {
	Name            string
	Support         string
	WallpaperDark   string
	WallpaperLight  string
}

func LoadOfficial(path string) (*Official, error) {
	if path == "" {
		var err error
		path, err = assets.OfficialCatalog()
		if err != nil {
			return nil, err
		}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cat Official
	if err := json.Unmarshal(raw, &cat); err != nil {
		return nil, fmt.Errorf("official catalog: %w", err)
	}
	if cat.SchemaVersion != 1 {
		return nil, fmt.Errorf("official catalog: schema_version %d not supported", cat.SchemaVersion)
	}
	if len(cat.Distros) == 0 {
		return nil, fmt.Errorf("official catalog: empty")
	}
	return &cat, nil
}

func (c *Official) Distro(id string) *Distro {
	for i := range c.Distros {
		if c.Distros[i].ID == id {
			return &c.Distros[i]
		}
	}
	return nil
}

func (d *Distro) DefaultEdition() *Edition {
	for i := range d.Editions {
		if d.Editions[i].Default {
			return &d.Editions[i]
		}
	}
	if len(d.Editions) > 0 {
		return &d.Editions[0]
	}
	return nil
}

func (d *Distro) Stageable() bool {
	if !d.CanStage || d.Install == nil || *d.Install == "" {
		return false
	}
	ed := d.DefaultEdition()
	return ed != nil && ed.Pinned()
}

func (e *Edition) Pinned() bool {
	return e.URL != nil && *e.URL != "" &&
		e.SHA256 != nil && looksSHA256(*e.SHA256) &&
		e.SizeBytes != nil && *e.SizeBytes > 0
}

func looksSHA256(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, c := range s {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

func ValidateRetailer(r Retailer) error {
	if err := oneLine("Shop name", r.Name, 1, 80); err != nil {
		return err
	}
	if err := oneLine("Support", r.Support, 1, 160); err != nil {
		return err
	}
	if r.WallpaperDark == "" || r.WallpaperLight == "" {
		return fmt.Errorf("choose a dark wallpaper and a light wallpaper")
	}
	if !assets.FileExists(r.WallpaperDark) {
		return fmt.Errorf("dark wallpaper not found")
	}
	if !assets.FileExists(r.WallpaperLight) {
		return fmt.Errorf("light wallpaper not found")
	}
	return nil
}

func oneLine(label, s string, min, max int) error {
	s = strings.TrimSpace(s)
	if strings.ContainsAny(s, "\n\r") {
		return fmt.Errorf("%s must be a single line", label)
	}
	n := utf8.RuneCountInString(s)
	if n < min {
		return fmt.Errorf("%s is required", label)
	}
	if n > max {
		return fmt.Errorf("%s is too long", label)
	}
	return nil
}

func RetailerFile(r Retailer) string {
	return fmt.Sprintf(
		"schema_version = 1\nname = %s\nsupport = %s\nwallpaper_dark = wallpapers/dark.jpg\nwallpaper_light = wallpapers/light.jpg\n",
		sanitizeValue(r.Name),
		sanitizeValue(r.Support),
	)
}

func sanitizeValue(s string) string {
	s = strings.TrimSpace(s)
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.ReplaceAll(s, "\r", "")
	return s
}

// BuildShop turns the ticked official ids into a shop catalog.json.
// Each ticked distro is recommended; its default edition is local. Other
// pinned editions of that distro stay as downloads. Unticked rows are omitted
// (shop catalog cannot carry install: null).
func BuildShop(off *Official, stagedIDs []string) (*Shop, error) {
	if len(stagedIDs) == 0 {
		return nil, fmt.Errorf("pick at least one distro to keep on the USB")
	}
	seen := map[string]bool{}
	shop := &Shop{SchemaVersion: 1, Recommended: []ShopDistro{}, Catalog: []ShopDistro{}}
	for _, id := range stagedIDs {
		if seen[id] {
			return nil, fmt.Errorf("duplicate distro %s", id)
		}
		seen[id] = true
		d := off.Distro(id)
		if d == nil {
			return nil, fmt.Errorf("unknown distro %s", id)
		}
		if !d.Stageable() {
			return nil, fmt.Errorf("%s cannot be staged yet", d.Name)
		}
		sd, err := shopDistro(d)
		if err != nil {
			return nil, err
		}
		shop.Recommended = append(shop.Recommended, sd)
	}
	return shop, nil
}

func shopDistro(d *Distro) (ShopDistro, error) {
	sd := ShopDistro{
		ID:          d.ID,
		Name:        d.Name,
		Version:     d.Version,
		Tagline:     d.Tagline,
		Description: d.Description,
		Family:      d.Family,
		Install:     *d.Install,
	}
	var haveDefault bool
	for _, ed := range d.Editions {
		if !ed.Pinned() {
			if ed.Default {
				return sd, fmt.Errorf("%s %s is not pinned (url / sha256 / size)", d.Name, ed.Name)
			}
			continue
		}
		se := ShopEdition{
			ID:        ed.ID,
			Name:      ed.Name,
			Default:   ed.Default,
			SHA256:    *ed.SHA256,
			SizeBytes: *ed.SizeBytes,
		}
		if ed.Default {
			se.Local = true
			se.File = "images/" + ed.Filename
			haveDefault = true
		} else {
			se.Local = false
			se.URL = *ed.URL
		}
		sd.Editions = append(sd.Editions, se)
	}
	if !haveDefault {
		return sd, fmt.Errorf("%s has no pinned default edition", d.Name)
	}
	return sd, nil
}

func (s *Shop) LocalEditions() []ShopEdition {
	var out []ShopEdition
	for _, d := range s.Recommended {
		for _, e := range d.Editions {
			if e.Local {
				out = append(out, e)
			}
		}
	}
	return out
}

func (s *Shop) LocalBytes() int64 {
	var n int64
	for _, e := range s.LocalEditions() {
		n += e.SizeBytes
	}
	return n
}

func (s *Shop) LargestLocal() int64 {
	var n int64
	for _, e := range s.LocalEditions() {
		if e.SizeBytes > n {
			n = e.SizeBytes
		}
	}
	return n
}

func FormatBytes(n int64) string {
	const (
		kib = 1024
		mib = 1024 * kib
		gib = 1024 * mib
	)
	switch {
	case n >= gib:
		return fmt.Sprintf("%.1f GB", float64(n)/float64(gib))
	case n >= mib:
		return fmt.Sprintf("%.0f MB", float64(n)/float64(mib))
	case n >= kib:
		return fmt.Sprintf("%.0f KB", float64(n)/float64(kib))
	default:
		return fmt.Sprintf("%d B", n)
	}
}

func StickSuggestion(need int64) int {
	// Advertised stick size is larger than usable space. Leave shop headroom.
	switch {
	case need <= 7<<30:
		return 16
	case need <= 24<<30:
		return 32
	case need <= 48<<30:
		return 64
	case need <= 100<<30:
		return 128
	default:
		return 256
	}
}

func DiskSuggestion(need, largestISO int64) int {
	// USB contents copied onto the PC, plus room to unpack the largest staged ISO.
	pc := need + largestISO + 16<<30
	return StickSuggestion(pc)
}
