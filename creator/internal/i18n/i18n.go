// Package i18n loads GNU gettext catalogs for the USB Creator GUI.
// English (US) is the source; other languages are po/ catalogs.
package i18n

import (
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
)

const (
	DefaultLanguage = "en-us"
	configName      = "ui-language"
)

var (
	cacheMu  sync.Mutex
	catalogs = map[string]map[string]string{}
)

func Canonical(id string) string {
	return catalog.CanonicalLanguage(id)
}

func isEnglish(id string) bool {
	return id == "en" || strings.HasPrefix(id, "en-")
}

func HasCatalog(id string) bool {
	id = Canonical(id)
	if id == "" {
		return false
	}
	if id == DefaultLanguage || isEnglish(id) {
		return true
	}
	_, err := assets.CatalogPO(id)
	return err == nil
}

func Resolve(id string) string {
	langs, _ := catalog.LoadLanguages("")
	id = Canonical(id)
	if catalog.ValidLanguage(id, langs) && HasCatalog(id) {
		return id
	}
	return DefaultLanguage
}

func Supported(langs []catalog.Language) []catalog.Language {
	out := make([]catalog.Language, 0, len(langs))
	for _, lang := range langs {
		if HasCatalog(lang.ID) {
			out = append(out, lang)
		}
	}
	hasEnglish := false
	for _, lang := range out {
		if isEnglish(lang.ID) {
			hasEnglish = true
			break
		}
	}
	if !hasEnglish {
		out = append([]catalog.Language{{
			ID: DefaultLanguage, Name: "English (US)", En: "English (US)",
		}}, out...)
	}
	return out
}

func CatalogFor(id string) map[string]string {
	id = Resolve(id)
	if id == DefaultLanguage || id == "en" {
		return map[string]string{}
	}
	cacheMu.Lock()
	if cat, ok := catalogs[id]; ok {
		cacheMu.Unlock()
		return cat
	}
	cacheMu.Unlock()
	path, err := assets.CatalogPO(id)
	if err != nil {
		return map[string]string{}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return map[string]string{}
	}
	cat := ParsePO(string(raw))
	cacheMu.Lock()
	catalogs[id] = cat
	cacheMu.Unlock()
	return cat
}

func T(lang, msgid string) string {
	if msgid == "" {
		return msgid
	}
	if cat := CatalogFor(lang); cat != nil {
		if dst, ok := cat[msgid]; ok && dst != "" {
			return dst
		}
	}
	return msgid
}

func Format(lang, msgid string, args map[string]string) string {
	out := T(lang, msgid)
	for k, v := range args {
		out = strings.ReplaceAll(out, "{"+k+"}", v)
	}
	return out
}

func ConfigPath() string {
	if env := os.Getenv("FIRSTBOOT_UI_LANGUAGE_FILE"); env != "" {
		return env
	}
	dir, err := os.UserConfigDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", configName)
	}
	return filepath.Join(dir, "firstboot", configName)
}

func Load() string {
	path := ConfigPath()
	raw, err := os.ReadFile(path)
	if err != nil {
		return DefaultLanguage
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		return Resolve(line)
	}
	return DefaultLanguage
}

func Save(id string) (string, error) {
	lid := Resolve(id)
	path := ConfigPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return lid, err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(lid+"\n"), 0o644); err != nil {
		return lid, err
	}
	if err := os.Rename(tmp, path); err != nil {
		return lid, err
	}
	return lid, nil
}

// ParsePO is a minimal GNU gettext .po reader (msgid / msgstr only).
func ParsePO(text string) map[string]string {
	out := map[string]string{}
	var msgid []string
	var msgstr []string
	var state string

	flush := func() {
		if msgid != nil && msgstr != nil {
			src := strings.Join(msgid, "")
			dst := strings.Join(msgstr, "")
			if src != "" && dst != "" {
				out[src] = dst
			}
		}
		msgid = nil
		msgstr = nil
		state = ""
	}

	for _, raw := range strings.Split(text, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "msgid ") {
			flush()
			msgid = []string{}
			msgstr = nil
			state = "msgid"
			if chunk, ok := unquotePO(strings.TrimSpace(line[6:])); ok {
				msgid = append(msgid, chunk)
			}
			continue
		}
		if strings.HasPrefix(line, "msgstr ") {
			msgstr = []string{}
			state = "msgstr"
			if chunk, ok := unquotePO(strings.TrimSpace(line[7:])); ok {
				msgstr = append(msgstr, chunk)
			}
			continue
		}
		if strings.HasPrefix(line, "msgctxt ") || strings.HasPrefix(line, "msgid_plural ") {
			flush()
			state = ""
			continue
		}
		if (state == "msgid" || state == "msgstr") && strings.HasPrefix(line, "\"") {
			chunk, ok := unquotePO(line)
			if !ok {
				continue
			}
			if state == "msgid" && msgid != nil {
				msgid = append(msgid, chunk)
			} else if state == "msgstr" && msgstr != nil {
				msgstr = append(msgstr, chunk)
			}
		}
	}
	flush()
	return out
}

func unquotePO(token string) (string, bool) {
	token = strings.TrimSpace(token)
	if len(token) < 2 || token[0] != '"' || token[len(token)-1] != '"' {
		return "", false
	}
	inner := token[1 : len(token)-1]
	var b strings.Builder
	b.Grow(len(inner))
	for i := 0; i < len(inner); i++ {
		ch := inner[i]
		if ch != '\\' {
			b.WriteByte(ch)
			continue
		}
		i++
		if i >= len(inner) {
			break
		}
		switch inner[i] {
		case 'n':
			b.WriteByte('\n')
		case 't':
			b.WriteByte('\t')
		case 'r':
			b.WriteByte('\r')
		case '\\':
			b.WriteByte('\\')
		case '"':
			b.WriteByte('"')
		default:
			b.WriteByte(inner[i])
		}
	}
	return b.String(), true
}
