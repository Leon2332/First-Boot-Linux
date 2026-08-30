package catalog

import (
	"archive/zip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadZipAndBuildShopTwoEditions(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "pack")
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	man := `{
  "schema_version": 1,
  "id": "pop-os",
  "name": "Pop!_OS",
  "version": "22.04 / 24.04 LTS",
  "tagline": "COSMIC and GNOME from System76",
  "description": "A polished desktop.",
  "family": "other",
  "install": "pop-os",
  "logo": "logo.png",
  "driver": "driver.py",
  "editions": [
    {"id": "gnome", "name": "GNOME", "default": true, "filename": "pop-os_22.04_amd64_intel.iso"},
    {"id": "cosmic", "name": "COSMIC", "default": false, "filename": "pop-os_24.04_amd64_intel.iso"}
  ]
}`
	if err := os.WriteFile(filepath.Join(src, "manifest.json"), []byte(man), 0o644); err != nil {
		t.Fatal(err)
	}
	driver := "ID = \"pop-os\"\nDRIVER = object()\n"
	if err := os.WriteFile(filepath.Join(src, "driver.py"), []byte(driver), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "logo.png"), []byte("png"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(src, "locale"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(
		filepath.Join(src, "locale", "af.po"),
		[]byte("msgid \"COSMIC and GNOME from System76\"\nmsgstr \"COSMIC en GNOME van System76\"\n"),
		0o644,
	); err != nil {
		t.Fatal(err)
	}
	isoA := []byte("gnome-iso-bytes")
	isoB := []byte("cosmic-iso-bytes-longer")
	if err := os.WriteFile(filepath.Join(src, "pop-os_22.04_amd64_intel.iso"), isoA, 0o644); err != nil {
		t.Fatal(err)
	}
	zipPath := filepath.Join(dir, "pop-os-fbl.zip")
	if err := zipDir(zipPath, src, []string{
		"manifest.json", "driver.py", "logo.png", "locale/af.po", "pop-os_22.04_amd64_intel.iso",
	}); err != nil {
		t.Fatal(err)
	}
	cosmicISO := filepath.Join(dir, "isos", "pop-os_24.04_amd64_intel.iso")
	if err := os.MkdirAll(filepath.Dir(cosmicISO), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cosmicISO, isoB, 0o644); err != nil {
		t.Fatal(err)
	}

	off, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	cache := filepath.Join(dir, "images")
	dest := filepath.Join(dir, "extracted")
	pack, err := LoadZip(zipPath, dest, cache, off)
	if err != nil {
		t.Fatal(err)
	}
	if pack.ID != "pop-os" || pack.Install != "pop-os" || len(pack.Editions) != 2 {
		t.Fatalf("pack %+v", pack)
	}
	if pack.LocaleFile("af") == "" {
		t.Fatal("af.po should be extracted from the zip")
	}
	if pack.LocaleFile("en-us") != "" {
		t.Fatal("en-us must not have a pack catalog")
	}
	gnome := pack.Edition("gnome")
	if gnome == nil || !pack.CanStageEdition(*gnome) {
		t.Fatalf("gnome should pick ISO from the zip: %+v", gnome)
	}
	cosmic := pack.Edition("cosmic")
	if cosmic == nil || cosmic.ISOPath != "" {
		t.Fatalf("cosmic should wait for an ISO: %+v", cosmic)
	}
	if err := AttachISO(pack, "cosmic", cosmicISO); err != nil {
		t.Fatal(err)
	}
	if !pack.CanStageEdition(*pack.Edition("cosmic")) {
		t.Fatal("cosmic should be stageable after AttachISO")
	}

	shop, err := BuildShop(off, []string{"pop-os:gnome", "pop-os:cosmic"}, pack)
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) < 1 || shop.Recommended[0].ID != "pop-os" {
		t.Fatalf("recommended %+v", shop.Recommended)
	}
	pop := shop.Recommended[0]
	if pop.Install != "pop-os" || pop.Family != "other" || len(pop.Editions) != 2 {
		t.Fatalf("shop row %+v", pop)
	}
	if pop.SecureBoot {
		t.Fatal("pack without secure_boot must not claim Secure Boot")
	}
	if !pop.Editions[0].Local || pop.Editions[0].File != "images/pop-os_22.04_amd64_intel.iso" {
		t.Fatalf("gnome edition %+v", pop.Editions[0])
	}
	if !pop.Editions[1].Local || pop.Editions[1].File != "images/pop-os_24.04_amd64_intel.iso" {
		t.Fatalf("cosmic edition %+v", pop.Editions[1])
	}
	if !pop.Editions[0].Default || pop.Editions[1].Default {
		t.Fatalf("featured should stay pack default (gnome): %+v", pop.Editions)
	}
	if got := shopIDs(shop.Catalog); len(got) != 3 {
		t.Fatalf("official distros should stay downloads, catalog %+v", got)
	}

	if _, err := BuildShop(off, []string{"ubuntu"}, pack); err != nil {
		t.Fatalf("official still works: %v", err)
	}
	if _, err := LoadZip(zipPath, dest, cache, off); err != nil {
		t.Fatal(err)
	}
}

func TestPackLocaleLang(t *testing.T) {
	cases := map[string]string{
		"locale/af.po":                       "af",
		"af.po":                              "af",
		"locale/en-gb.po":                    "en-gb",
		"locale/en_ZA.po":                    "en-za",
		"locale/af/LC_MESSAGES/firstboot.po": "af",
	}
	for rel, want := range cases {
		got, ok := packLocaleLang(rel)
		if !ok || got != want {
			t.Errorf("%s: got %s %v, want %s", rel, got, ok, want)
		}
	}
	for _, rel := range []string{"driver.py", "en-us.po", "locale/en.po", "images/af.po"} {
		if _, ok := packLocaleLang(rel); ok {
			t.Errorf("%s should not be a pack locale", rel)
		}
	}
}

func TestAttachISOPinnedHash(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "pack")
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	iso := []byte("pop-iso-bytes")
	man := `{
  "schema_version": 1,
  "id": "pop-os",
  "name": "Pop!_OS",
  "version": "24.04 LTS",
  "tagline": "t",
  "description": "d",
  "family": "other",
  "install": "pop-os",
  "editions": [
    {"id": "cosmic", "name": "COSMIC", "default": true, "filename": "pop-os_24.04_amd64_generic_27.iso", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ]
}`
	if err := os.WriteFile(filepath.Join(src, "manifest.json"), []byte(man), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "driver.py"), []byte("ID = \"pop-os\"\nDRIVER = object()\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "logo.png"), []byte("png"), 0o644); err != nil {
		t.Fatal(err)
	}
	zipPath := filepath.Join(dir, "pack.zip")
	if err := zipDir(zipPath, src, []string{"manifest.json", "driver.py", "logo.png"}); err != nil {
		t.Fatal(err)
	}
	off, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	pack, err := LoadZip(zipPath, filepath.Join(dir, "extracted"), filepath.Join(dir, "images"), off)
	if err != nil {
		t.Fatal(err)
	}
	isoPath := filepath.Join(dir, "pop-os_24.04_amd64_generic_27.iso")
	if err := os.WriteFile(isoPath, iso, 0o644); err != nil {
		t.Fatal(err)
	}
	err = AttachISO(pack, "cosmic", isoPath)
	if err == nil || !strings.Contains(err.Error(), "sha256") {
		t.Fatalf("want sha256 mismatch, got %v", err)
	}

	want, err := hashFile(isoPath)
	if err != nil {
		t.Fatal(err)
	}
	ed := pack.Edition("cosmic")
	ed.PinSHA256 = want
	if err := AttachISO(pack, "cosmic", isoPath); err != nil {
		t.Fatal(err)
	}
	if pack.Edition("cosmic").SHA256 != want {
		t.Fatalf("hash %s", pack.Edition("cosmic").SHA256)
	}
}

func TestPackManifestRejectsBadSHA256(t *testing.T) {
	_, err := parsePackManifest([]byte(`{
  "schema_version": 1,
  "id": "pop-os",
  "name": "Pop",
  "version": "1",
  "tagline": "t",
  "description": "d",
  "family": "other",
  "install": "pop-os",
  "editions": [{"id": "gnome", "name": "GNOME", "default": true, "filename": "a.iso", "sha256": "not-a-hash"}]
}`))
	if err == nil {
		t.Fatal("bad sha256")
	}
}

func TestReservedPackID(t *testing.T) {
	off, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	if !ReservedPackID("ubuntu", off) || !ReservedPackID("ubuntu-2604", off) {
		t.Fatal("ubuntu is reserved")
	}
	if ReservedPackID("pop-os", off) {
		t.Fatal("pop-os should be allowed")
	}
}

func TestPackManifestRejectsBadInstall(t *testing.T) {
	_, err := parsePackManifest([]byte(`{
  "schema_version": 1,
  "id": "pop-os",
  "name": "Pop",
  "version": "1",
  "tagline": "t",
  "description": "d",
  "family": "other",
  "install": "ubuntu-2604",
  "editions": [{"id": "gnome", "name": "GNOME", "default": true, "filename": "a.iso"}]
}`))
	if err == nil {
		t.Fatal("install must equal id")
	}
}

func zipDir(dest, src string, names []string) error {
	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()
	zw := zip.NewWriter(f)
	for _, name := range names {
		w, err := zw.Create(name)
		if err != nil {
			zw.Close()
			return err
		}
		raw, err := os.ReadFile(filepath.Join(src, name))
		if err != nil {
			zw.Close()
			return err
		}
		if _, err := w.Write(raw); err != nil {
			zw.Close()
			return err
		}
	}
	return zw.Close()
}
