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
	ID               string    `json:"id"`
	Name             string    `json:"name"`
	Version          string    `json:"version"`
	Tagline          string    `json:"tagline"`
	Description      string    `json:"description"`
	Family           string    `json:"family"`
	Redistributable  bool      `json:"redistributable"`
	Install          *string   `json:"install"`
	CanStage         bool      `json:"can_stage"`
	SuggestedDefault bool      `json:"suggested_default"`
	SecureBoot       bool      `json:"secure_boot"`
	Editions         []Edition `json:"editions"`
}

type Edition struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Default   bool    `json:"default"`
	Install   *string `json:"install,omitempty"`
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
	SecureBoot  bool          `json:"secure_boot"`
	Editions    []ShopEdition `json:"editions"`
}

type ShopEdition struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Default   bool   `json:"default"`
	Local     bool   `json:"local"`
	Install   string `json:"install,omitempty"`
	File      string `json:"file,omitempty"`
	URL       string `json:"url,omitempty"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
}

type Language struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	En   string `json:"en"`
}

type languageFile struct {
	SchemaVersion int        `json:"schema_version"`
	Languages     []Language `json:"languages"`
}

type Keyboard struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type keyboardFile struct {
	SchemaVersion int        `json:"schema_version"`
	Keyboards     []Keyboard `json:"keyboards"`
}

type Retailer struct {
	Name           string
	Support        string
	WallpaperDark  string
	WallpaperLight string
	Language       string
	Keyboard       string
	Timezone       string
}

var languageAliases = map[string]string{
	"en":    "en-us",
	"af-za": "af",
}

func CanonicalLanguage(id string) string {
	id = strings.ToLower(strings.TrimSpace(id))
	id = strings.ReplaceAll(id, "_", "-")
	if a, ok := languageAliases[id]; ok {
		return a
	}
	return id
}

func isEnglishID(id string) bool {
	return id == "en" || strings.HasPrefix(id, "en-")
}

func CanonicalKeyboard(id string) string {
	return strings.ToLower(strings.TrimSpace(id))
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

func (d *Distro) Edition(id string) *Edition {
	for i := range d.Editions {
		if d.Editions[i].ID == id {
			return &d.Editions[i]
		}
	}
	return nil
}

func (d *Distro) CanStageEdition(ed Edition) bool {
	if !d.Redistributable || !d.CanStage || d.Install == nil || *d.Install == "" {
		return false
	}
	return ed.Pinned()
}

func (d *Distro) Stageable() bool {
	for _, ed := range d.Editions {
		if d.CanStageEdition(ed) {
			return true
		}
	}
	return false
}

// Offerable is true when the shop catalog may list this distro.
// Redistributable rows need can_stage. Non-redistributable rows need install
// and a pinned default; they go in recommended as download-only.
func (d *Distro) Offerable() bool {
	if d.Install == nil || *d.Install == "" {
		return false
	}
	ed := d.DefaultEdition()
	if ed == nil || !ed.Pinned() {
		return false
	}
	if d.Stageable() {
		return true
	}
	return !d.Redistributable
}

func (d *Distro) NameMatches(query string) bool {
	return nameMatches(d.Name, query)
}

func nameMatches(name, query string) bool {
	toks := strings.Fields(strings.ToLower(strings.TrimSpace(query)))
	if len(toks) == 0 {
		return true
	}
	field := strings.ToLower(name)
	for _, tok := range toks {
		if !strings.Contains(field, tok) {
			return false
		}
	}
	return true
}

func StagedKey(distroID, editionID string) string {
	return distroID + ":" + editionID
}

func ParseStaged(spec string) (distroID, editionID string, err error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return "", "", fmt.Errorf("empty selection")
	}
	distroID, editionID, ok := strings.Cut(spec, ":")
	if !ok {
		return spec, "", nil
	}
	if distroID == "" || editionID == "" {
		return "", "", fmt.Errorf("invalid selection %s", spec)
	}
	return distroID, editionID, nil
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

func LoadLanguages(path string) ([]Language, error) {
	if path == "" {
		var err error
		path, err = assets.LanguagesJSON()
		if err != nil {
			return fallbackLanguages(), nil
		}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return fallbackLanguages(), nil
	}
	var file languageFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return nil, fmt.Errorf("languages: %w", err)
	}
	out := make([]Language, 0, len(file.Languages))
	seen := map[string]bool{}
	for _, lang := range file.Languages {
		id := CanonicalLanguage(lang.ID)
		name := strings.TrimSpace(lang.Name)
		if id == "" || name == "" || seen[id] {
			continue
		}
		seen[id] = true
		en := strings.TrimSpace(lang.En)
		if en == "" {
			en = name
		}
		out = append(out, Language{ID: id, Name: name, En: en})
	}
	hasEnglish := false
	for id := range seen {
		if isEnglishID(id) {
			hasEnglish = true
			break
		}
	}
	if !hasEnglish {
		out = append([]Language{{ID: "en-us", Name: "English (US)", En: "English (US)"}}, out...)
	}
	if len(out) == 0 {
		return fallbackLanguages(), nil
	}
	return out, nil
}

func fallbackLanguages() []Language {
	return []Language{
		{ID: "en-us", Name: "English (US)", En: "English (US)"},
		{ID: "en-gb", Name: "English (UK)", En: "English (UK)"},
		{ID: "en-za", Name: "English (South Africa)", En: "English (South Africa)"},
		{ID: "af", Name: "Afrikaans", En: "Afrikaans"},
	}
}

func ValidLanguage(id string, langs []Language) bool {
	id = CanonicalLanguage(id)
	if id == "" {
		return false
	}
	for _, lang := range langs {
		if lang.ID == id {
			return true
		}
	}
	return false
}

func NormalizeRetailerLanguage(id string, langs []Language) string {
	id = CanonicalLanguage(id)
	if ValidLanguage(id, langs) {
		return id
	}
	return "en-us"
}

func LoadKeyboards(path string) ([]Keyboard, error) {
	if path == "" {
		var err error
		path, err = assets.KeyboardsJSON()
		if err != nil {
			return fallbackKeyboards(), nil
		}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return fallbackKeyboards(), nil
	}
	var file keyboardFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return nil, fmt.Errorf("keyboards: %w", err)
	}
	out := make([]Keyboard, 0, len(file.Keyboards))
	seen := map[string]bool{}
	for _, kb := range file.Keyboards {
		id := CanonicalKeyboard(kb.ID)
		name := strings.TrimSpace(kb.Name)
		if id == "" || name == "" || seen[id] {
			continue
		}
		seen[id] = true
		out = append(out, Keyboard{ID: id, Name: name})
	}
	if !seen["us"] {
		out = append([]Keyboard{{ID: "us", Name: "English (US)"}}, out...)
	}
	if len(out) == 0 {
		return fallbackKeyboards(), nil
	}
	return out, nil
}

func fallbackKeyboards() []Keyboard {
	return []Keyboard{
		{ID: "us", Name: "English (US)"},
		{ID: "gb", Name: "English (UK)"},
	}
}

func ValidKeyboard(id string, boards []Keyboard) bool {
	id = CanonicalKeyboard(id)
	if id == "" {
		return false
	}
	for _, kb := range boards {
		if kb.ID == id {
			return true
		}
	}
	return false
}

func NormalizeRetailerKeyboard(id string, boards []Keyboard) string {
	id = CanonicalKeyboard(id)
	if ValidKeyboard(id, boards) {
		return id
	}
	return "us"
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
	langs, err := LoadLanguages("")
	if err != nil {
		return err
	}
	if r.Language != "" && !ValidLanguage(r.Language, langs) {
		return fmt.Errorf("unknown default language")
	}
	boards, err := LoadKeyboards("")
	if err != nil {
		return err
	}
	if r.Keyboard != "" && !ValidKeyboard(r.Keyboard, boards) {
		return fmt.Errorf("unknown keyboard layout")
	}
	if r.Timezone != "" && !ValidTimezone(r.Timezone) {
		return fmt.Errorf("unknown default time zone")
	}
	return nil
}

const (
	tzMin  = -12 * 60
	tzMax  = 14 * 60
	tzStep = 30
)

func SnapTZ(minutes int) int {
	if minutes < 0 {
		minutes = -((-minutes + tzStep/2) / tzStep * tzStep)
	} else {
		minutes = (minutes + tzStep/2) / tzStep * tzStep
	}
	if minutes < tzMin {
		return tzMin
	}
	if minutes > tzMax {
		return tzMax
	}
	return minutes
}

func FormatTZ(minutes int) string {
	minutes = SnapTZ(minutes)
	sign := "+"
	abs := minutes
	if minutes < 0 {
		sign = "-"
		abs = -minutes
	}
	return fmt.Sprintf("UTC%s%02d%02d", sign, abs/60, abs%60)
}

func ParseTZ(s string) (int, bool) {
	s = strings.ToUpper(strings.TrimSpace(s))
	s = strings.ReplaceAll(s, " ", "")
	s = strings.ReplaceAll(s, ":", "")
	if strings.HasPrefix(s, "UTC") {
		s = s[3:]
	}
	if s == "" || s == "0" || s == "00" || s == "0000" {
		return 0, true
	}
	if len(s) < 2 || (s[0] != '+' && s[0] != '-') {
		return 0, false
	}
	sign := 1
	if s[0] == '-' {
		sign = -1
	}
	digits := s[1:]
	for _, c := range digits {
		if c < '0' || c > '9' {
			return 0, false
		}
	}
	hours, mins := 0, 0
	switch len(digits) {
	case 1, 2:
		fmt.Sscanf(digits, "%d", &hours)
	case 3:
		hours = int(digits[0] - '0')
		fmt.Sscanf(digits[1:], "%d", &mins)
	case 4:
		fmt.Sscanf(digits[:2], "%d", &hours)
		fmt.Sscanf(digits[2:], "%d", &mins)
	default:
		return 0, false
	}
	if mins != 0 && mins != 30 {
		return 0, false
	}
	total := sign * (hours*60 + mins)
	if total < tzMin || total > tzMax {
		return 0, false
	}
	return total, true
}

func ValidTimezone(s string) bool {
	_, ok := ParseTZ(s)
	return ok
}

func NormalizeRetailerTimezone(s string) string {
	minutes, ok := ParseTZ(s)
	if !ok {
		return "UTC+0000"
	}
	return FormatTZ(minutes)
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
	lang := CanonicalLanguage(r.Language)
	if lang == "" {
		lang = "en-us"
	}
	kbd := CanonicalKeyboard(r.Keyboard)
	if kbd == "" {
		kbd = "us"
	}
	tz := NormalizeRetailerTimezone(r.Timezone)
	return fmt.Sprintf(
		"schema_version = 1\nname = %s\nsupport = %s\nwallpaper_dark = wallpapers/dark.jpg\nwallpaper_light = wallpapers/light.jpg\nlanguage = %s\nkeyboard = %s\ntimezone = %s\n",
		sanitizeValue(r.Name),
		sanitizeValue(r.Support),
		sanitizeValue(lang),
		sanitizeValue(kbd),
		sanitizeValue(tz),
	)
}

func sanitizeValue(s string) string {
	s = strings.TrimSpace(s)
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.ReplaceAll(s, "\r", "")
	return s
}

// BuildShop turns ticked desktops into a shop catalog.json.
// Each spec is distro:edition (linux-mint:cinnamon). A bare distro id
// means that distro's default edition.
// A distro with any ticked desktop is recommended: ticked stageable
// editions are local (chooser recommended cards, one per desktop);
// other pinned editions stay as downloads. Ticked editions are listed
// first, in selection order. The featured edition is the official
// default if ticked, otherwise the first ticked desktop. Unticked
// offerable distros go in catalog as download-only — Other options on
// the chooser. Rows with install: null stay out.
func BuildShop(off *Official, selected []string, packs ...*Pack) (*Shop, error) {
	if len(selected) == 0 {
		return nil, fmt.Errorf("tick at least one desktop to keep on the USB")
	}
	picked := map[string][]string{}
	order := []string{}
	seen := map[string]bool{}
	for _, spec := range selected {
		did, eid, err := ParseStaged(spec)
		if err != nil {
			return nil, err
		}
		d := off.Distro(did)
		p := PackByID(packs, did)
		if d == nil && p == nil {
			return nil, fmt.Errorf("unknown distro %s", did)
		}
		if d != nil && p != nil {
			return nil, fmt.Errorf("%s is an official id", did)
		}
		if d != nil {
			if !d.Offerable() {
				return nil, fmt.Errorf("%s cannot be offered yet", d.Name)
			}
			if eid == "" {
				ed := d.DefaultEdition()
				if ed == nil {
					return nil, fmt.Errorf("%s has no default desktop", d.Name)
				}
				eid = ed.ID
			}
			if d.Edition(eid) == nil {
				return nil, fmt.Errorf("unknown desktop %s for %s", eid, d.Name)
			}
		} else {
			if eid == "" {
				ed := p.DefaultEdition()
				if ed == nil {
					return nil, fmt.Errorf("%s has no default desktop", p.Name)
				}
				eid = ed.ID
			}
			ed := p.Edition(eid)
			if ed == nil {
				return nil, fmt.Errorf("unknown desktop %s for %s", eid, p.Name)
			}
			if !p.CanStageEdition(*ed) {
				return nil, fmt.Errorf("choose an ISO for %s %s", p.Name, ed.Name)
			}
		}
		key := StagedKey(did, eid)
		if seen[key] {
			return nil, fmt.Errorf("duplicate desktop %s", key)
		}
		seen[key] = true
		if _, ok := picked[did]; !ok {
			order = append(order, did)
		}
		picked[did] = append(picked[did], eid)
	}
	shop := &Shop{SchemaVersion: 1, Recommended: []ShopDistro{}, Catalog: []ShopDistro{}}
	for _, did := range order {
		if d := off.Distro(did); d != nil {
			sd, err := shopDistro(d, picked[did])
			if err != nil {
				return nil, err
			}
			shop.Recommended = append(shop.Recommended, sd)
			continue
		}
		sd, err := shopDistroFromPack(PackByID(packs, did), picked[did])
		if err != nil {
			return nil, err
		}
		shop.Recommended = append(shop.Recommended, sd)
	}
	for i := range off.Distros {
		d := &off.Distros[i]
		if _, ok := picked[d.ID]; ok {
			continue
		}
		if !d.Offerable() {
			continue
		}
		sd, err := shopDistro(d, nil)
		if err != nil {
			return nil, err
		}
		shop.Catalog = append(shop.Catalog, sd)
	}
	return shop, nil
}

func shopDistroFromPack(p *Pack, selected []string) (ShopDistro, error) {
	if p == nil {
		return ShopDistro{}, fmt.Errorf("missing pack")
	}
	if len(selected) == 0 {
		return ShopDistro{}, fmt.Errorf("tick at least one desktop for %s", p.Name)
	}
	sd := ShopDistro{
		ID:          p.ID,
		Name:        p.Name,
		Version:     p.Version,
		Tagline:     p.Tagline,
		Description: p.Description,
		Family:      p.Family,
		Install:     p.Install,
		SecureBoot:  p.SecureBoot,
	}
	featured := ""
	if def := p.DefaultEdition(); def != nil {
		for _, id := range selected {
			if id == def.ID {
				featured = def.ID
				break
			}
		}
	}
	if featured == "" {
		featured = selected[0]
	}
	seen := map[string]bool{}
	for _, eid := range selected {
		if seen[eid] {
			continue
		}
		seen[eid] = true
		ed := p.Edition(eid)
		if ed == nil {
			return sd, fmt.Errorf("unknown desktop %s for %s", eid, p.Name)
		}
		if !p.CanStageEdition(*ed) {
			return sd, fmt.Errorf("choose an ISO for %s %s", p.Name, ed.Name)
		}
		sd.Editions = append(sd.Editions, ShopEdition{
			ID:        ed.ID,
			Name:      ed.Name,
			Default:   ed.ID == featured,
			Local:     true,
			File:      p.File(*ed),
			SHA256:    ed.SHA256,
			SizeBytes: ed.SizeBytes,
		})
	}
	return sd, nil
}

func shopDistro(d *Distro, selected []string) (ShopDistro, error) {
	sd := ShopDistro{
		ID:          d.ID,
		Name:        d.Name,
		Version:     d.Version,
		Tagline:     d.Tagline,
		Description: d.Description,
		Family:      d.Family,
		Install:     *d.Install,
		SecureBoot:  d.SecureBoot,
	}
	picked := map[string]bool{}
	for _, id := range selected {
		picked[id] = true
	}
	featured := featuredEdition(d, selected)
	var haveFeatured bool
	for _, ed := range orderedEditions(d, selected) {
		if !ed.Pinned() {
			if ed.Default {
				return sd, fmt.Errorf("%s %s is not pinned (url / sha256 / size)", d.Name, ed.Name)
			}
			continue
		}
		se := ShopEdition{
			ID:        ed.ID,
			Name:      ed.Name,
			Default:   featured != "" && ed.ID == featured,
			SHA256:    *ed.SHA256,
			SizeBytes: *ed.SizeBytes,
		}
		if ed.Install != nil && *ed.Install != "" && *ed.Install != *d.Install {
			se.Install = *ed.Install
		}
		if picked[ed.ID] && d.CanStageEdition(ed) {
			se.Local = true
			se.File = "images/" + ed.Filename
		} else {
			se.Local = false
			se.URL = *ed.URL
		}
		if se.Default {
			haveFeatured = true
		}
		sd.Editions = append(sd.Editions, se)
	}
	if !haveFeatured {
		return sd, fmt.Errorf("%s has no pinned default edition", d.Name)
	}
	return sd, nil
}

func orderedEditions(d *Distro, selected []string) []Edition {
	seen := map[string]bool{}
	out := make([]Edition, 0, len(d.Editions))
	for _, eid := range selected {
		ed := d.Edition(eid)
		if ed == nil || seen[eid] {
			continue
		}
		seen[eid] = true
		out = append(out, *ed)
	}
	for _, ed := range d.Editions {
		if seen[ed.ID] {
			continue
		}
		out = append(out, ed)
	}
	return out
}

func featuredEdition(d *Distro, selected []string) string {
	if len(selected) > 0 {
		picked := map[string]bool{}
		for _, id := range selected {
			picked[id] = true
		}
		if def := d.DefaultEdition(); def != nil && picked[def.ID] {
			return def.ID
		}
		return selected[0]
	}
	if def := d.DefaultEdition(); def != nil {
		return def.ID
	}
	return ""
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
