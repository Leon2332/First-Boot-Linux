package ui

import (
	"bytes"
	"encoding/json"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/i18n"
)

func TestLanguageButtonInPage(t *testing.T) {
	raw, err := webFS.ReadFile("web/index.html")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		`id="ui-lang-btn"`,
		`id="ui-lang-pop"`,
		`id="ui-lang-list"`,
		`data-i18n="Shop details"`,
		`data-i18n="USB creator"`,
		`id="pack-file"`,
	} {
		if !bytes.Contains(raw, []byte(want)) {
			t.Fatalf("missing %s", want)
		}
	}
	js, err := webFS.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(js, []byte("Add your own")) {
		t.Fatal("missing Add your own")
	}
	css, err := webFS.ReadFile("web/styles.css")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(css, []byte(".pack-remove")) || !bytes.Contains(css, []byte(".card-head")) {
		t.Fatal("missing pack remove styles")
	}
	if !bytes.Contains(js, []byte("sb-pill")) || !bytes.Contains(css, []byte(".sb-pill")) {
		t.Fatal("missing Secure Boot pill")
	}
	if !bytes.Contains(js, []byte("pack-pill")) || !bytes.Contains(css, []byte(".pack-pill")) {
		t.Fatal("missing Retailer pack pill")
	}
	if bytes.Contains(js, []byte("No Secure Boot")) {
		t.Fatal("creator cards must not label missing Secure Boot")
	}
	if !bytes.Contains(css, []byte(".lang-pop")) || !bytes.Contains(css, []byte(".lang-btn")) {
		t.Fatal("missing language popover styles")
	}
}

func TestStateServesUICatalog(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("FIRSTBOOT_UI_LANGUAGE_FILE", filepath.Join(dir, "ui-language"))
	if _, err := i18n.Save("af"); err != nil {
		t.Fatal(err)
	}
	off, err := catalog.LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	s := &session{off: off}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/state", nil)
	s.state(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status %d %s", rec.Code, rec.Body.String())
	}
	var out struct {
		UILanguage string             `json:"ui_language"`
		Catalog    map[string]string  `json:"catalog"`
		Languages  []catalog.Language `json:"languages"`
		Distros    []struct {
			ID         string `json:"id"`
			SecureBoot bool   `json:"secure_boot"`
		} `json:"distros"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out.UILanguage != "af" {
		t.Fatalf("ui_language %s", out.UILanguage)
	}
	if out.Catalog["USB creator"] != "USB-skepper" {
		t.Fatalf("catalog %#v", out.Catalog["USB creator"])
	}
	if out.Catalog["Shop details"] != "Winkelbesonderhede" {
		t.Fatal("missing shop details")
	}
	ids := map[string]bool{}
	for _, lang := range out.Languages {
		ids[lang.ID] = true
	}
	if !ids["en-us"] || !ids["af"] {
		t.Fatalf("languages %#v", out.Languages)
	}
	found := false
	for _, d := range out.Distros {
		if d.ID == "ubuntu" {
			found = true
			if !d.SecureBoot {
				t.Fatal("ubuntu must advertise Secure Boot")
			}
		}
	}
	if !found {
		t.Fatal("ubuntu missing from state")
	}
}

func TestSetUILanguage(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "ui-language")
	t.Setenv("FIRSTBOOT_UI_LANGUAGE_FILE", file)
	s := &session{off: &catalog.Official{SchemaVersion: 1}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/ui-language", strings.NewReader(`{"language":"af"}`))
	s.setUILanguage(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status %d %s", rec.Code, rec.Body.String())
	}
	var out struct {
		Language string            `json:"language"`
		Catalog  map[string]string `json:"catalog"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out.Language != "af" || out.Catalog["Continue"] != "Gaan voort" {
		t.Fatalf("%#v", out)
	}
	raw, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	if string(raw) != "af\n" {
		t.Fatalf("persisted %q", raw)
	}
	rec = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodPost, "/api/ui-language", strings.NewReader(`{"language":"en-us"}`))
	s.setUILanguage(rec, req)
	out = struct {
		Language string            `json:"language"`
		Catalog  map[string]string `json:"catalog"`
	}{}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out.Language != "en-us" || len(out.Catalog) != 0 {
		t.Fatalf("en-us should be source, got language=%s catalog entries=%d", out.Language, len(out.Catalog))
	}
}

func TestRemoveCustomPack(t *testing.T) {
	s := &session{
		off: &catalog.Official{SchemaVersion: 1},
		packs: []*catalog.Pack{
			{ID: "pop-os", Name: "Pop!_OS"},
			{ID: "tuxedo-os", Name: "TUXEDO OS"},
		},
	}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/custom-remove?id=pop-os", strings.NewReader(`{"id":"pop-os"}`))
	s.removePack(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status %d %s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("cache-control %q", rec.Header().Get("Cache-Control"))
	}
	if len(s.packs) != 1 || s.packs[0].ID != "tuxedo-os" {
		t.Fatalf("packs after remove: %#v", s.packs)
	}

	s.packs = []*catalog.Pack{{ID: "pop-os", Name: "Pop!_OS"}}
	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(mustSubFS(t)))
	mux.HandleFunc("POST /api/custom-remove", s.removePack)
	mux.HandleFunc("/api/custom-remove", s.removePack)
	rec = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodPost, "/api/custom-remove", strings.NewReader(`{"id":"pop-os"}`))
	mux.ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("mux status %d %s", rec.Code, rec.Body.String())
	}
	if len(s.packs) != 0 {
		t.Fatalf("mux packs after remove: %#v", s.packs)
	}

	js, err := webFS.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		`function removePack(id)`,
		`d.id !== id`,
		`ticked.splice(i, 1)`,
		`data-pack-id=`,
		`cache: "no-store"`,
		`e.target.closest(".pack-remove")`,
	} {
		if !bytes.Contains(js, []byte(want)) {
			t.Fatalf("app.js missing %s", want)
		}
	}
}

func mustSubFS(t *testing.T) http.FileSystem {
	t.Helper()
	static, err := fs.Sub(webFS, "web")
	if err != nil {
		t.Fatal(err)
	}
	return http.FS(static)
}
