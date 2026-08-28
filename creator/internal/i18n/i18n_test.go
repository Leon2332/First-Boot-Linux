package i18n

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode"
)

func TestParsePOEscapes(t *testing.T) {
	cat := ParsePO("msgid \"Say \\\"hi\\\"\\n\"\nmsgstr \"Sê \\\"hallo\\\"\\n\"\n")
	if got := cat["Say \"hi\"\n"]; got != "Sê \"hallo\"\n" {
		t.Fatalf("got %q", got)
	}
}

func TestCatalogAfrikaans(t *testing.T) {
	if T(DefaultLanguage, "Network") != "Network" {
		t.Fatal("en-us is the source")
	}
	if T("en", "Network") != "Network" {
		t.Fatal("en aliases to en-us")
	}
	if T("af", "Network") != "Netwerk" {
		t.Fatalf("got %q", T("af", "Network"))
	}
	if T("af", "USB creator") != "USB-skepper" {
		t.Fatalf("creator string: %q", T("af", "USB creator"))
	}
	if T("af", "Language") != "Taal" {
		t.Fatal("shared chooser string should load")
	}
	if Format("af", "Downloading {name}", map[string]string{"name": "Ubuntu"}) != "Laai Ubuntu af" {
		t.Fatalf("format: %q", Format("af", "Downloading {name}", map[string]string{"name": "Ubuntu"}))
	}
	if T("en-gb", "Maximize") != "Maximise" {
		t.Fatalf("en-gb: %q", T("en-gb", "Maximize"))
	}
	if Resolve("de") != DefaultLanguage {
		t.Fatal("unknown language falls back to en-us")
	}
	if Resolve("EN") != "en-us" {
		t.Fatal("EN → en-us")
	}
	if Resolve("en-GB") != "en-gb" {
		t.Fatal("en-GB stays en-gb")
	}
	if !HasCatalog("en-us") || !HasCatalog("af") || !HasCatalog("en-gb") {
		t.Fatal("shipped catalogs")
	}
	if HasCatalog("de") {
		t.Fatal("de is not shipped")
	}
}

func TestGeenHasNoTrailingNie(t *testing.T) {
	cat := CatalogFor("af")
	if len(cat) == 0 {
		t.Fatal("af catalog empty")
	}
	for src, dst := range cat {
		cleaned := strings.Map(func(r rune) rune {
			if unicode.IsPunct(r) {
				return ' '
			}
			return unicode.ToLower(r)
		}, dst)
		words := strings.Fields(cleaned)
		if len(words) == 0 {
			continue
		}
		hasGeen := false
		for _, w := range words {
			if w == "geen" {
				hasGeen = true
				break
			}
		}
		if hasGeen && words[len(words)-1] == "nie" {
			t.Fatalf("geen must not take a trailing nie: %q → %q", src, dst)
		}
	}
}

func TestPersistUILanguage(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("FIRSTBOOT_UI_LANGUAGE_FILE", "")
	path := filepath.Join(dir, "firstboot", "ui-language")
	if Load() != DefaultLanguage {
		t.Fatal("missing file is en-us")
	}
	got, err := Save("AF")
	if err != nil {
		t.Fatal(err)
	}
	if got != "af" {
		t.Fatalf("save returned %s", got)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(raw) != "af\n" {
		t.Fatalf("file %q", raw)
	}
	if Load() != "af" {
		t.Fatalf("load %s", Load())
	}
	if _, err := Save("en"); err != nil {
		t.Fatal(err)
	}
	if Load() != "en-us" {
		t.Fatal("en should persist as en-us")
	}
}

func TestParseSkipsHeader(t *testing.T) {
	cat := ParsePO("msgid \"\"\nmsgstr \"Language: af\\n\"\n\nmsgid \"Back\"\nmsgstr \"Terug\"\n")
	if _, ok := cat[""]; ok {
		t.Fatal("empty msgid should be skipped")
	}
	if cat["Back"] != "Terug" {
		t.Fatalf("got %#v", cat)
	}
}
