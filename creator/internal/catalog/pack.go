package catalog

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

const (
	packSchemaVersion  = 1
	maxPackMetaBytes   = 8 << 20
	maxPackLogoBytes   = 8 << 20
	maxPackDriverBytes = 2 << 20
	maxPackLocaleBytes = 512 << 10
)

// ReservedInstallIDs are baked-in or reserved catalog install ids. A shop
// pack must not reuse them. ubuntu-2604-gnome and mint-223-{cinnamon,mate,xfce}
// are live native drivers; the other ubuntu/mint/fedora ids are retired
// trampolines kept reserved so packs cannot claim them.
var ReservedInstallIDs = map[string]bool{
	"ubuntu-2604-gnome":     true,
	"ubuntu-2604":           true,
	"ubuntu-autoinstall":    true,
	"ubuntu-calamares-2604": true,
	"mint-223-cinnamon":     true,
	"mint-223-mate":         true,
	"mint-223-xfce":         true,
	"mint-223":              true,
	"mint":                  true,
	"fedora-44-plasma":      true,
	"fedora-kickstart":      true,
	"debian-preseed":        true,
	"windows":               true,
	"freebsd":               true,
}

type Pack struct {
	ID          string
	Name        string
	Version     string
	Tagline     string
	Description string
	Family      string
	Install     string
	SecureBoot  bool
	Dir         string
	Manifest    string
	DriverPath  string
	LogoPath    string
	ZipPath     string
	Editions    []PackEdition
}

type PackEdition struct {
	ID        string
	Name      string
	Filename  string
	Default   bool
	ISOPath   string
	SHA256    string
	SizeBytes int64
	PinSHA256 string
	PinSize   int64
}

type packManifest struct {
	SchemaVersion int                   `json:"schema_version"`
	ID            string                `json:"id"`
	Name          string                `json:"name"`
	Version       string                `json:"version"`
	Tagline       string                `json:"tagline"`
	Description   string                `json:"description"`
	Family        string                `json:"family"`
	Install       string                `json:"install"`
	Logo          string                `json:"logo"`
	Driver        string                `json:"driver"`
	SecureBoot    bool                  `json:"secure_boot"`
	Editions      []packManifestEdition `json:"editions"`
}

type packManifestEdition struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Default   bool   `json:"default"`
	Filename  string `json:"filename"`
	SHA256    string `json:"sha256"`
	SizeBytes *int64 `json:"size_bytes"`
}

func (p *Pack) Edition(id string) *PackEdition {
	if p == nil {
		return nil
	}
	for i := range p.Editions {
		if p.Editions[i].ID == id {
			return &p.Editions[i]
		}
	}
	return nil
}

func (p *Pack) DefaultEdition() *PackEdition {
	if p == nil {
		return nil
	}
	for i := range p.Editions {
		if p.Editions[i].Default {
			return &p.Editions[i]
		}
	}
	if len(p.Editions) > 0 {
		return &p.Editions[0]
	}
	return nil
}

func (p *Pack) CanStageEdition(ed PackEdition) bool {
	return ed.ISOPath != "" && looksSHA256(ed.SHA256) && ed.SizeBytes > 0
}

func (p *Pack) File(ed PackEdition) string {
	return "images/" + ed.Filename
}

func (p *Pack) LocaleDir() string {
	if p == nil || p.Dir == "" {
		return ""
	}
	return filepath.Join(p.Dir, "locale")
}

func (p *Pack) LocaleFile(lang string) string {
	lang = CanonicalLanguage(lang)
	if p == nil || lang == "" || lang == "en" || lang == "en-us" {
		return ""
	}
	path := filepath.Join(p.LocaleDir(), lang+".po")
	if fileExists(path) {
		return path
	}
	return ""
}

func PackByID(packs []*Pack, id string) *Pack {
	for _, p := range packs {
		if p != nil && p.ID == id {
			return p
		}
	}
	return nil
}

func ReservedPackID(id string, off *Official) bool {
	id = strings.TrimSpace(id)
	if id == "" || ReservedInstallIDs[id] {
		return true
	}
	if id == "ms-windows" {
		return true
	}
	if off != nil && off.Distro(id) != nil {
		return true
	}
	return false
}

func ValidPackID(id string) bool {
	if id == "" {
		return false
	}
	for i, c := range id {
		if c >= 'a' && c <= 'z' || c >= '0' && c <= '9' {
			continue
		}
		if c == '-' && i > 0 && i < len(id)-1 {
			continue
		}
		return false
	}
	return true
}

func PackCacheDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", "packs")
	}
	return filepath.Join(home, ".cache", "firstboot", "packs")
}

// LoadZip extracts a retailer pack into destRoot/<id>/ and attaches ISOs
// found in the zip, next to the zip, or in imageCache.
func LoadZip(zipPath, destRoot, imageCache string, off *Official) (*Pack, error) {
	zipPath, err := filepath.Abs(zipPath)
	if err != nil {
		return nil, err
	}
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return nil, fmt.Errorf("open pack: %w", err)
	}
	defer zr.Close()

	prefix, err := zipPrefix(zr.File)
	if err != nil {
		return nil, err
	}
	raw, err := zipRead(zr, prefix+"manifest.json", maxPackMetaBytes)
	if err != nil {
		return nil, fmt.Errorf("manifest.json: %w", err)
	}
	man, err := parsePackManifest(raw)
	if err != nil {
		return nil, err
	}
	if ReservedPackID(man.ID, off) {
		return nil, fmt.Errorf("%s is reserved; pick another pack id", man.ID)
	}

	if destRoot == "" {
		destRoot = PackCacheDir()
	}
	dir := filepath.Join(destRoot, man.ID)
	if err := os.RemoveAll(dir); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}

	driverName := man.Driver
	if driverName == "" {
		driverName = "driver.py"
	}
	logoName := man.Logo
	if logoName == "" {
		logoName = "logo.png"
	}
	driverPath := filepath.Join(dir, "driver.py")
	logoPath := filepath.Join(dir, filepath.Base(logoName))
	manifestPath := filepath.Join(dir, "manifest.json")
	if err := os.WriteFile(manifestPath, raw, 0o644); err != nil {
		return nil, err
	}
	if err := zipExtractFile(zr, prefix+driverName, driverPath, maxPackDriverBytes); err != nil {
		return nil, fmt.Errorf("%s: %w", driverName, err)
	}
	if err := zipExtractFile(zr, prefix+logoName, logoPath, maxPackLogoBytes); err != nil {
		return nil, fmt.Errorf("%s: %w", logoName, err)
	}
	if err := packDriverLooksOK(driverPath, man.ID); err != nil {
		return nil, err
	}
	if err := extractPackLocales(zr, prefix, dir); err != nil {
		return nil, err
	}

	p := &Pack{
		ID:          man.ID,
		Name:        man.Name,
		Version:     man.Version,
		Tagline:     man.Tagline,
		Description: man.Description,
		Family:      man.Family,
		Install:     man.Install,
		SecureBoot:  man.SecureBoot,
		Dir:         dir,
		Manifest:    manifestPath,
		DriverPath:  driverPath,
		LogoPath:    logoPath,
		ZipPath:     zipPath,
	}
	beside := filepath.Dir(zipPath)
	for _, ed := range man.Editions {
		pe := PackEdition{
			ID:        ed.ID,
			Name:      ed.Name,
			Filename:  ed.Filename,
			Default:   ed.Default,
			PinSHA256: ed.SHA256,
		}
		if ed.SizeBytes != nil {
			pe.PinSize = *ed.SizeBytes
		}
		if zipFile(zr, prefix+ed.Filename) != nil {
			isoDest := filepath.Join(imageCacheOr(imageCache), ed.Filename)
			if err := zipExtractFile(zr, prefix+ed.Filename, isoDest, 0); err != nil {
				return nil, fmt.Errorf("%s: %w", ed.Filename, err)
			}
			pe.ISOPath = isoDest
		}
		if pe.ISOPath == "" {
			for _, c := range []string{
				filepath.Join(beside, ed.Filename),
				filepath.Join(imageCacheOr(imageCache), ed.Filename),
			} {
				if fileExists(c) {
					pe.ISOPath = c
					break
				}
			}
		}
		if pe.ISOPath != "" {
			if err := HashISO(&pe); err != nil {
				return nil, fmt.Errorf("%s: %w", ed.Filename, err)
			}
		}
		p.Editions = append(p.Editions, pe)
	}
	return p, nil
}

func extractPackLocales(zr *zip.ReadCloser, prefix, destDir string) error {
	localeDir := filepath.Join(destDir, "locale")
	for _, f := range zr.File {
		if f.FileInfo().IsDir() {
			continue
		}
		name := filepath.ToSlash(f.Name)
		if prefix != "" {
			if !strings.HasPrefix(name, prefix) {
				continue
			}
			name = strings.TrimPrefix(name, prefix)
		}
		lang, ok := packLocaleLang(name)
		if !ok {
			continue
		}
		dest := filepath.Join(localeDir, lang+".po")
		if err := zipExtractFile(zr, filepath.ToSlash(f.Name), dest, maxPackLocaleBytes); err != nil {
			return fmt.Errorf("locale/%s.po: %w", lang, err)
		}
	}
	return nil
}

func packLocaleLang(rel string) (string, bool) {
	rel = strings.TrimPrefix(filepath.ToSlash(rel), "/")
	if rel == "" || strings.Contains(rel, "..") {
		return "", false
	}
	base := filepath.Base(rel)
	dir := filepath.ToSlash(filepath.Dir(rel))
	if strings.ToLower(filepath.Ext(base)) != ".po" {
		return "", false
	}
	stem := strings.ToLower(strings.TrimSuffix(base, filepath.Ext(base)))
	stem = strings.ReplaceAll(stem, "_", "-")
	switch dir {
	case ".", "":
		return localeIDFromStem(stem)
	case "locale":
		return localeIDFromStem(stem)
	default:
		parts := strings.Split(dir, "/")
		if len(parts) >= 2 && parts[0] == "locale" && strings.EqualFold(stem, "firstboot") {
			return localeIDFromStem(CanonicalLanguage(parts[1]))
		}
	}
	return "", false
}

func localeIDFromStem(stem string) (string, bool) {
	stem = CanonicalLanguage(stem)
	if stem == "" || stem == "en" || stem == "en-us" {
		return "", false
	}
	if !validLocaleID(stem) {
		return "", false
	}
	return stem, true
}

var localeIDRe = regexp.MustCompile(`^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$`)

func validLocaleID(id string) bool {
	return localeIDRe.MatchString(id)
}

func imageCacheOr(dir string) string {
	if dir != "" {
		return dir
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", "images")
	}
	return filepath.Join(home, ".cache", "firstboot", "images")
}

func HashISO(ed *PackEdition) error {
	if ed == nil || ed.ISOPath == "" {
		return fmt.Errorf("no ISO")
	}
	st, err := os.Stat(ed.ISOPath)
	if err != nil {
		return err
	}
	if st.IsDir() || st.Size() < 1 {
		return fmt.Errorf("ISO is empty")
	}
	sum, err := hashFile(ed.ISOPath)
	if err != nil {
		return err
	}
	if ed.PinSHA256 != "" && sum != ed.PinSHA256 {
		return fmt.Errorf("sha256 does not match the pack")
	}
	if ed.PinSize > 0 && st.Size() != ed.PinSize {
		return fmt.Errorf("size does not match the pack")
	}
	ed.SHA256 = sum
	ed.SizeBytes = st.Size()
	return nil
}

func AttachISO(p *Pack, editionID, path string) error {
	if p == nil {
		return fmt.Errorf("no pack")
	}
	ed := p.Edition(editionID)
	if ed == nil {
		return fmt.Errorf("unknown desktop %s", editionID)
	}
	path = strings.TrimSpace(path)
	if path == "" {
		return fmt.Errorf("choose an ISO")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	ext := strings.ToLower(filepath.Ext(abs))
	if ext != ".iso" && ext != ".img" {
		return fmt.Errorf("use an .iso or .img")
	}
	ed.ISOPath = abs
	if err := HashISO(ed); err != nil {
		ed.ISOPath = ""
		ed.SHA256 = ""
		ed.SizeBytes = 0
		return err
	}
	return nil
}

func pinEdition(ed packManifestEdition) (string, int64, error) {
	pin := strings.ToLower(strings.TrimSpace(ed.SHA256))
	if pin != "" && !looksSHA256(pin) {
		return "", 0, fmt.Errorf("sha256 must be 64 lowercase hex")
	}
	var size int64
	if ed.SizeBytes != nil {
		if *ed.SizeBytes < 1 {
			return "", 0, fmt.Errorf("size_bytes must be positive")
		}
		size = *ed.SizeBytes
	}
	return pin, size, nil
}

func parsePackManifest(raw []byte) (*packManifest, error) {
	var man packManifest
	if err := json.Unmarshal(raw, &man); err != nil {
		return nil, fmt.Errorf("manifest.json: %w", err)
	}
	if man.SchemaVersion != packSchemaVersion {
		return nil, fmt.Errorf("manifest.json: schema_version %d not supported", man.SchemaVersion)
	}
	man.ID = strings.TrimSpace(man.ID)
	man.Install = strings.TrimSpace(man.Install)
	if man.Install == "" {
		man.Install = man.ID
	}
	if !ValidPackID(man.ID) {
		return nil, fmt.Errorf("manifest.json: invalid id")
	}
	if man.Install != man.ID {
		return nil, fmt.Errorf("manifest.json: install must equal id")
	}
	if err := oneLine("name", man.Name, 1, 80); err != nil {
		return nil, fmt.Errorf("manifest.json: %w", err)
	}
	if err := oneLine("version", man.Version, 1, 40); err != nil {
		return nil, fmt.Errorf("manifest.json: %w", err)
	}
	if strings.TrimSpace(man.Tagline) == "" || utf8.RuneCountInString(man.Tagline) > 160 {
		return nil, fmt.Errorf("manifest.json: tagline is required")
	}
	if strings.TrimSpace(man.Description) == "" {
		return nil, fmt.Errorf("manifest.json: description is required")
	}
	switch man.Family {
	case "ubuntu", "mint", "fedora", "debian", "suse", "windows", "bsd", "other":
	default:
		return nil, fmt.Errorf("manifest.json: unknown family")
	}
	if man.Logo == "" {
		man.Logo = "logo.png"
	}
	if man.Driver == "" {
		man.Driver = "driver.py"
	}
	if strings.ContainsAny(man.Logo, `/\`) || strings.ContainsAny(man.Driver, `/\`) {
		return nil, fmt.Errorf("manifest.json: logo and driver must be basenames")
	}
	if len(man.Editions) == 0 {
		return nil, fmt.Errorf("manifest.json: need at least one desktop")
	}
	seen := map[string]bool{}
	files := map[string]bool{}
	defaults := 0
	for i, ed := range man.Editions {
		ed.ID = strings.TrimSpace(ed.ID)
		ed.Name = strings.TrimSpace(ed.Name)
		ed.Filename = strings.TrimSpace(ed.Filename)
		if !ValidPackID(ed.ID) {
			return nil, fmt.Errorf("manifest.json: editions[%d] invalid id", i)
		}
		if ed.Name == "" {
			return nil, fmt.Errorf("manifest.json: editions[%d] name is required", i)
		}
		if seen[ed.ID] {
			return nil, fmt.Errorf("manifest.json: duplicate desktop %s", ed.ID)
		}
		seen[ed.ID] = true
		if !packFilenameOK(ed.Filename) {
			return nil, fmt.Errorf("manifest.json: editions[%d] filename must be a .iso or .img basename", i)
		}
		if files[ed.Filename] {
			return nil, fmt.Errorf("manifest.json: duplicate filename %s", ed.Filename)
		}
		files[ed.Filename] = true
		if ed.Default {
			defaults++
		}
		pin, size, err := pinEdition(ed)
		if err != nil {
			return nil, fmt.Errorf("manifest.json: editions[%d] %w", i, err)
		}
		ed.SHA256 = pin
		if size > 0 {
			ed.SizeBytes = &size
		}
		man.Editions[i] = ed
	}
	if defaults != 1 {
		return nil, fmt.Errorf("manifest.json: exactly one default desktop")
	}
	return &man, nil
}

func packFilenameOK(name string) bool {
	if name == "" || strings.ContainsAny(name, `/\`) {
		return false
	}
	ext := strings.ToLower(filepath.Ext(name))
	return ext == ".iso" || ext == ".img"
}

func packDriverLooksOK(path, id string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	text := string(raw)
	if !strings.Contains(text, "DRIVER") {
		return fmt.Errorf("driver.py must export DRIVER")
	}
	if !strings.Contains(text, id) {
		return fmt.Errorf("driver.py must use install id %s", id)
	}
	return nil
}

func zipPrefix(files []*zip.File) (string, error) {
	var names []string
	for _, f := range files {
		name := filepath.ToSlash(f.Name)
		if name == "" || strings.HasPrefix(name, "__MACOSX/") {
			continue
		}
		if strings.Contains(name, "..") {
			return "", fmt.Errorf("pack path escapes the zip")
		}
		if strings.HasPrefix(name, "/") {
			return "", fmt.Errorf("pack path is absolute")
		}
		names = append(names, name)
	}
	if len(names) == 0 {
		return "", fmt.Errorf("empty pack")
	}
	for _, n := range names {
		if n == "manifest.json" || strings.HasPrefix(n, "manifest.json/") {
			return "", nil
		}
	}
	first := names[0]
	slash := strings.IndexByte(first, '/')
	if slash < 1 {
		return "", fmt.Errorf("manifest.json is missing")
	}
	top := first[:slash+1]
	for _, n := range names {
		if n != strings.TrimSuffix(top, "/") && !strings.HasPrefix(n, top) {
			return "", fmt.Errorf("manifest.json is missing")
		}
	}
	if zipHas(files, top+"manifest.json") {
		return top, nil
	}
	return "", fmt.Errorf("manifest.json is missing")
}

func zipHas(files []*zip.File, name string) bool {
	for _, f := range files {
		if filepath.ToSlash(f.Name) == name && !f.FileInfo().IsDir() {
			return true
		}
	}
	return false
}

func zipFile(zr *zip.ReadCloser, name string) *zip.File {
	name = filepath.ToSlash(name)
	for _, f := range zr.File {
		if filepath.ToSlash(f.Name) == name && !f.FileInfo().IsDir() {
			return f
		}
	}
	return nil
}

func zipRead(zr *zip.ReadCloser, name string, max int64) ([]byte, error) {
	f := zipFile(zr, name)
	if f == nil {
		return nil, fmt.Errorf("not in the zip")
	}
	if max > 0 && f.UncompressedSize64 > uint64(max) {
		return nil, fmt.Errorf("file is too large")
	}
	rc, err := f.Open()
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	var r io.Reader = rc
	if max > 0 {
		r = io.LimitReader(rc, max+1)
	}
	raw, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	if max > 0 && int64(len(raw)) > max {
		return nil, fmt.Errorf("file is too large")
	}
	return raw, nil
}

func zipExtractFile(zr *zip.ReadCloser, name, dest string, max int64) error {
	f := zipFile(zr, name)
	if f == nil {
		return fmt.Errorf("not in the zip")
	}
	if max > 0 && f.UncompressedSize64 > uint64(max) {
		return fmt.Errorf("file is too large")
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()
	out, err := os.OpenFile(dest, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	defer out.Close()
	var r io.Reader = rc
	if max > 0 {
		r = io.LimitReader(rc, max+1)
	}
	n, err := io.Copy(out, r)
	if err != nil {
		return err
	}
	if max > 0 && n > max {
		_ = os.Remove(dest)
		return fmt.Errorf("file is too large")
	}
	return nil
}

func hashFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func fileExists(path string) bool {
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}
