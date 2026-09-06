package catalog

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadOfficialAndStageable(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	u := cat.Distro("ubuntu")
	if u == nil || !u.Redistributable || !u.Stageable() {
		t.Fatalf("ubuntu should be redistributable and stageable")
	}
	if u.Install == nil || *u.Install != "ubuntu-2604-gnome" {
		t.Fatalf("ubuntu install %v", u.Install)
	}
	if !u.SecureBoot {
		t.Fatal("ubuntu must support Secure Boot")
	}
	if u.DefaultEdition() == nil || u.DefaultEdition().SHA256 == nil {
		t.Fatalf("ubuntu default edition not pinned")
	}
	if *u.DefaultEdition().SizeBytes != 6518974464 {
		t.Fatalf("ubuntu size %v", u.DefaultEdition().SizeBytes)
	}
	if u.SuggestedDefault {
		t.Fatalf("nothing should be a suggested default")
	}
	m := cat.Distro("linux-mint")
	if m == nil || !m.Redistributable || !m.Stageable() {
		t.Fatalf("linux-mint should be redistributable and stageable")
	}
	if m.Install == nil || *m.Install != "mint-223-cinnamon" {
		t.Fatalf("mint install %v", m.Install)
	}
	if !m.SecureBoot {
		t.Fatal("mint must support Secure Boot")
	}
	if m.DefaultEdition() == nil || m.DefaultEdition().ID != "cinnamon" {
		t.Fatalf("mint default edition %+v", m.DefaultEdition())
	}
	if m.DefaultEdition().SHA256 == nil || *m.DefaultEdition().SizeBytes != 3091660800 {
		t.Fatalf("mint size %v", m.DefaultEdition().SizeBytes)
	}
	if len(m.Editions) != 3 {
		t.Fatalf("mint editions %d", len(m.Editions))
	}
	mate := m.Edition("mate")
	if mate == nil || mate.Install == nil || *mate.Install != "mint-223-mate" || *mate.SizeBytes != 3134275584 {
		t.Fatalf("mint mate %+v", mate)
	}
	xfce := m.Edition("xfce")
	if xfce == nil || xfce.Install == nil || *xfce.Install != "mint-223-xfce" || *xfce.SizeBytes != 3033710592 {
		t.Fatalf("mint xfce %+v", xfce)
	}
	if m.SuggestedDefault {
		t.Fatalf("nothing should be a suggested default")
	}
	f := cat.Distro("fedora")
	if f == nil || !f.Redistributable || !f.Stageable() {
		t.Fatalf("fedora should be redistributable and stageable")
	}
	if f.Install == nil || *f.Install != "fedora-44-plasma" {
		t.Fatalf("fedora install %v", f.Install)
	}
	if !f.SecureBoot {
		t.Fatal("fedora must support Secure Boot")
	}
	if f.DefaultEdition() == nil || f.DefaultEdition().ID != "plasma" {
		t.Fatalf("fedora default edition %+v", f.DefaultEdition())
	}
	if f.DefaultEdition().SHA256 == nil || *f.DefaultEdition().SizeBytes != 3368683520 {
		t.Fatalf("fedora size %v", f.DefaultEdition().SizeBytes)
	}
	if len(f.Editions) != 2 {
		t.Fatalf("fedora editions %d", len(f.Editions))
	}
	gnome := f.Edition("gnome")
	if gnome == nil || gnome.Install == nil || *gnome.Install != "fedora-44-gnome" || *gnome.SizeBytes != 2851612672 {
		t.Fatalf("fedora gnome %+v", gnome)
	}
	if f.SuggestedDefault {
		t.Fatalf("nothing should be a suggested default")
	}
	if len(cat.Distros) != 3 {
		t.Fatalf("official catalog should be Ubuntu GNOME + Linux Mint + Fedora, got %d", len(cat.Distros))
	}
	for _, id := range []string{"kubuntu", "lubuntu", "ubuntu-budgie", "ubuntu-mate", "xubuntu"} {
		if cat.Distro(id) != nil {
			t.Fatalf("%s should not be official until it has a native installer", id)
		}
	}
}

func TestBuildShop(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	shop, err := BuildShop(cat, []string{"ubuntu"})
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) != 1 {
		t.Fatalf("got rec=%d", len(shop.Recommended))
	}
	if len(shop.Catalog) != 2 || shop.Catalog[0].ID != "linux-mint" || shop.Catalog[1].ID != "fedora" {
		t.Fatalf("unticked mint and fedora should be catalog downloads, got %+v", shopIDs(shop.Catalog))
	}
	if shop.Catalog[0].Editions[0].Local || shop.Catalog[1].Editions[0].Local {
		t.Fatal("unticked mint and fedora must not be local")
	}
	ub := shop.Recommended[0]
	if !ub.SecureBoot {
		t.Fatal("shop ubuntu must keep secure_boot")
	}
	if !ub.Editions[0].Local || ub.Editions[0].File != "images/ubuntu-26.04-desktop-amd64.iso" {
		t.Fatalf("ubuntu edition %+v", ub.Editions[0])
	}
	if ub.Install != "ubuntu-2604-gnome" {
		t.Fatalf("install %s", ub.Install)
	}
	mintShop, err := BuildShop(cat, []string{"linux-mint:cinnamon"})
	if err != nil {
		t.Fatal(err)
	}
	if len(mintShop.Recommended) != 1 || mintShop.Recommended[0].ID != "linux-mint" {
		t.Fatalf("mint recommended %+v", mintShop.Recommended)
	}
	if mintShop.Recommended[0].Install != "mint-223-cinnamon" {
		t.Fatalf("mint install %s", mintShop.Recommended[0].Install)
	}
	ed := mintShop.Recommended[0].Editions[0]
	if !ed.Local || ed.File != "images/linuxmint-22.3-cinnamon-64bit.iso" {
		t.Fatalf("mint edition %+v", ed)
	}
	if len(mintShop.Recommended[0].Editions) != 3 {
		t.Fatalf("mint shop editions %d", len(mintShop.Recommended[0].Editions))
	}
	mateShop, err := BuildShop(cat, []string{"linux-mint:mate", "linux-mint:xfce"})
	if err != nil {
		t.Fatal(err)
	}
	if len(mateShop.Recommended) != 1 || mateShop.Recommended[0].Install != "mint-223-cinnamon" {
		t.Fatalf("mint distro install %s", mateShop.Recommended[0].Install)
	}
	eds := mateShop.Recommended[0].Editions
	if len(eds) != 3 || eds[0].ID != "mate" || !eds[0].Local || eds[0].Install != "mint-223-mate" {
		t.Fatalf("ticked mate %+v", eds)
	}
	if eds[1].ID != "xfce" || !eds[1].Local || eds[1].Install != "mint-223-xfce" {
		t.Fatalf("ticked xfce %+v", eds[1])
	}
	if eds[2].ID != "cinnamon" || eds[2].Local || eds[2].Install != "" {
		t.Fatalf("unticked cinnamon should inherit distro install, got %+v", eds[2])
	}
	fedoraShop, err := BuildShop(cat, []string{"fedora:plasma"})
	if err != nil {
		t.Fatal(err)
	}
	if len(fedoraShop.Recommended) != 1 || fedoraShop.Recommended[0].ID != "fedora" {
		t.Fatalf("fedora recommended %+v", fedoraShop.Recommended)
	}
	if fedoraShop.Recommended[0].Install != "fedora-44-plasma" {
		t.Fatalf("fedora install %s", fedoraShop.Recommended[0].Install)
	}
	fed := fedoraShop.Recommended[0].Editions[0]
	if !fed.Local || fed.File != "images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso" {
		t.Fatalf("fedora edition %+v", fed)
	}
	if len(fedoraShop.Recommended[0].Editions) != 2 {
		t.Fatalf("fedora shop editions %d", len(fedoraShop.Recommended[0].Editions))
	}
	gnomeShop, err := BuildShop(cat, []string{"fedora:gnome"})
	if err != nil {
		t.Fatal(err)
	}
	if len(gnomeShop.Recommended) != 1 || gnomeShop.Recommended[0].Install != "fedora-44-plasma" {
		t.Fatalf("fedora distro install %s", gnomeShop.Recommended[0].Install)
	}
	feds := gnomeShop.Recommended[0].Editions
	if len(feds) != 2 || feds[0].ID != "gnome" || !feds[0].Local || feds[0].Install != "fedora-44-gnome" {
		t.Fatalf("ticked gnome %+v", feds)
	}
	if feds[1].ID != "plasma" || feds[1].Local || feds[1].Install != "" {
		t.Fatalf("unticked plasma should inherit distro install, got %+v", feds[1])
	}
	if _, err := BuildShop(cat, nil); err == nil {
		t.Fatalf("empty selection must be rejected")
	}
}

func TestParseStagedAndNameMatches(t *testing.T) {
	did, eid, err := ParseStaged("linux-mint:cinnamon")
	if err != nil || did != "linux-mint" || eid != "cinnamon" {
		t.Fatalf("got %s %s %v", did, eid, err)
	}
	did, eid, err = ParseStaged("ubuntu")
	if err != nil || did != "ubuntu" || eid != "" {
		t.Fatalf("bare %s %s %v", did, eid, err)
	}
	if !nameMatches("Linux Mint", "mint") || !nameMatches("Linux Mint", "Linux  mint") {
		t.Fatal("mint should match")
	}
	if nameMatches("Linux Mint", "mate") || nameMatches("Ubuntu", "gnome") {
		t.Fatal("edition names must not match")
	}
	if nameMatches("Fedora", "windows") {
		t.Fatal("unrelated")
	}
}

func shopIDs(ds []ShopDistro) []string {
	out := make([]string, len(ds))
	for i, d := range ds {
		out[i] = d.ID
	}
	return out
}

func TestBuildShopDownloadOnlyRecommended(t *testing.T) {
	url := "https://example.invalid/windows.iso"
	sum := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	size := int64(6 << 30)
	install := "windows"
	off := &Official{
		SchemaVersion: 1,
		Distros: []Distro{
			{
				ID: "ubuntu", Name: "Ubuntu", Version: "26.04 LTS",
				Tagline: "t", Description: "d", Family: "ubuntu",
				Redistributable: true, Install: strp("ubuntu-autoinstall"),
				CanStage: true, SuggestedDefault: true,
				Editions: []Edition{{
					ID: "gnome", Name: "GNOME", Default: true,
					Filename: "ubuntu.iso", URL: &url, SHA256: &sum, SizeBytes: &size,
				}},
			},
			{
				ID: "ms-windows", Name: "MS Windows", Version: "11",
				Tagline: "t", Description: "d", Family: "windows",
				Redistributable: false, Install: &install,
				CanStage: false, SuggestedDefault: false,
				Editions: []Edition{{
					ID: "windows-11", Name: "Windows 11", Default: true,
					Filename: "windows.iso", URL: &url, SHA256: &sum, SizeBytes: &size,
				}},
			},
		},
	}
	if off.Distro("ms-windows").Stageable() {
		t.Fatal("windows must not be stageable")
	}
	if !off.Distro("ms-windows").Offerable() {
		t.Fatal("windows should be offerable as download-only")
	}
	shop, err := BuildShop(off, []string{"ubuntu", "ms-windows"})
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) != 2 {
		t.Fatalf("recommended %d", len(shop.Recommended))
	}
	win := shop.Recommended[1]
	if win.ID != "ms-windows" || win.Install != "windows" || win.Family != "windows" {
		t.Fatalf("windows row %+v", win)
	}
	if len(win.Editions) != 1 || win.Editions[0].Local || win.Editions[0].File != "" || win.Editions[0].URL == "" {
		t.Fatalf("windows must be download-only: %+v", win.Editions)
	}
	if !shop.Recommended[0].Editions[0].Local {
		t.Fatal("ubuntu should still be local")
	}
	if len(shop.LocalEditions()) != 1 {
		t.Fatalf("local editions %d", len(shop.LocalEditions()))
	}
}

func strp(s string) *string { return &s }

func TestRetailerFile(t *testing.T) {
	dir := t.TempDir()
	dark := filepath.Join(dir, "d.jpg")
	light := filepath.Join(dir, "l.jpg")
	if err := os.WriteFile(dark, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(light, []byte("y"), 0o644); err != nil {
		t.Fatal(err)
	}
	r := Retailer{Name: "Example Computers", Support: "support@example.com", WallpaperDark: dark, WallpaperLight: light}
	if err := ValidateRetailer(r); err != nil {
		t.Fatal(err)
	}
	got := RetailerFile(r)
	for _, want := range []string{
		"schema_version = 1",
		"name = Example Computers",
		"support = support@example.com",
		"wallpaper_dark = wallpapers/dark.jpg",
		"wallpaper_light = wallpapers/light.jpg",
		"language = en-us",
		"keyboard = us",
		"timezone = UTC+0000",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %s", want, got)
		}
	}
	if err := ValidateRetailer(Retailer{Name: "", Support: "x", WallpaperDark: dark, WallpaperLight: light}); err == nil {
		t.Fatalf("empty name should fail")
	}
}

func TestLoadLanguages(t *testing.T) {
	langs, err := LoadLanguages("")
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, lang := range langs {
		ids[lang.ID] = true
	}
	if !ids["en-us"] || !ids["en-gb"] || !ids["en-za"] || !ids["af"] {
		t.Fatalf("expected en-us, en-gb, en-za, and af, got %#v", langs)
	}
	if ids["en"] {
		t.Fatal("bare en should not be listed")
	}
	if ValidLanguage("de", langs) {
		t.Fatal("de is not shipped")
	}
	if !ValidLanguage("en", langs) {
		t.Fatal("en should alias to en-us")
	}
	if NormalizeRetailerLanguage("", langs) != "en-us" {
		t.Fatal("empty language should be en-us")
	}
	if NormalizeRetailerLanguage("EN", langs) != "en-us" {
		t.Fatal("EN should normalize to en-us")
	}
	if NormalizeRetailerLanguage("AF", langs) != "af" {
		t.Fatal("AF should normalize to af")
	}
	if NormalizeRetailerLanguage("en-GB", langs) != "en-gb" {
		t.Fatal("en-GB should stay en-gb")
	}
}

func TestLoadKeyboards(t *testing.T) {
	boards, err := LoadKeyboards("")
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, kb := range boards {
		ids[kb.ID] = true
	}
	if !ids["us"] || !ids["gb"] {
		t.Fatalf("expected us and gb, got %#v", boards)
	}
	if ValidKeyboard("nope", boards) {
		t.Fatal("nope is not a layout")
	}
	if NormalizeRetailerKeyboard("", boards) != "us" {
		t.Fatal("empty keyboard should be us")
	}
	if NormalizeRetailerKeyboard("GB", boards) != "gb" {
		t.Fatal("GB should normalize to gb")
	}
}

func TestTimezone(t *testing.T) {
	if got := FormatTZ(0); got != "UTC+0000" {
		t.Fatalf("0 → %s", got)
	}
	if got := FormatTZ(330); got != "UTC+0530" {
		t.Fatalf("330 → %s", got)
	}
	if got := FormatTZ(-300); got != "UTC-0500" {
		t.Fatalf("-300 → %s", got)
	}
	if m, ok := ParseTZ("UTC+0530"); !ok || m != 330 {
		t.Fatalf("parse +0530: %d %v", m, ok)
	}
	if m, ok := ParseTZ("utc-0500"); !ok || m != -300 {
		t.Fatalf("parse -0500: %d %v", m, ok)
	}
	if _, ok := ParseTZ("Europe/Paris"); ok {
		t.Fatal("named zone should fail")
	}
	if NormalizeRetailerTimezone("") != "UTC+0000" {
		t.Fatal("empty tz")
	}
	if NormalizeRetailerTimezone("UTC+2") != "UTC+0200" {
		t.Fatal("UTC+2")
	}
}

func TestStickSuggestion(t *testing.T) {
	if g := StickSuggestion(6 << 30); g != 16 {
		t.Fatalf("6G → %d", g)
	}
	if g := StickSuggestion(12 << 30); g != 32 {
		t.Fatalf("12G → %d", g)
	}
	if FormatBytes(6518974464) == "" {
		t.Fatal("format")
	}
}
