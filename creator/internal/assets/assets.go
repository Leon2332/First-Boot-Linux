package assets

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

var (
	exeOnce sync.Once
	exeDir  string
)

func ExecutableDir() string {
	exeOnce.Do(func() {
		p, err := os.Executable()
		if err != nil {
			exeDir, _ = os.Getwd()
			return
		}
		p, err = filepath.EvalSymlinks(p)
		if err != nil {
			exeDir = filepath.Dir(p)
			return
		}
		exeDir = filepath.Dir(p)
	})
	return exeDir
}

// RepoRoot walks from start (or the executable / cwd) until USB-LAYOUT.md
// and schemas/official-catalog.json are both present.
func RepoRoot(start string) (string, error) {
	seen := map[string]bool{}
	var roots []string
	if start != "" {
		roots = append(roots, start)
	}
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, wd)
	}
	roots = append(roots, ExecutableDir())
	for _, r := range roots {
		dir := r
		for i := 0; i < 12; i++ {
			abs, err := filepath.Abs(dir)
			if err != nil {
				break
			}
			if seen[abs] {
				break
			}
			seen[abs] = true
			if isRepo(abs) {
				return abs, nil
			}
			parent := filepath.Dir(abs)
			if parent == abs {
				break
			}
			dir = parent
		}
	}
	return "", errors.New("not inside the First Boot Linux tree")
}

func isRepo(dir string) bool {
	if !fileExists(filepath.Join(dir, "USB-LAYOUT.md")) {
		return false
	}
	return fileExists(filepath.Join(dir, "schemas", "official-catalog.json"))
}

func fileExists(path string) bool {
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}

func dirExists(path string) bool {
	st, err := os.Stat(path)
	return err == nil && st.IsDir()
}

// FirstExisting returns the first existing file or directory among paths.
func FirstExisting(paths ...string) (string, error) {
	for _, p := range paths {
		if p == "" {
			continue
		}
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	return "", fmt.Errorf("none of the paths exist")
}

// AppDir is the mounted or extracted AppImage directory (APPDIR).
func AppDir() string {
	d := os.Getenv("APPDIR")
	if d == "" || !dirExists(d) {
		return ""
	}
	return d
}

// AppImageFile is the path of the running AppImage (APPIMAGE), if any.
func AppImageFile() string {
	return os.Getenv("APPIMAGE")
}

// AppImageDir is the directory that contains the AppImage file.
func AppImageDir() string {
	p := AppImageFile()
	if p == "" {
		return ""
	}
	return filepath.Dir(p)
}

func sharePath(elem ...string) []string {
	var out []string
	if d := AppDir(); d != "" {
		out = append(out, filepath.Join(append([]string{d, "usr", "share", "firstboot"}, elem...)...))
		out = append(out, filepath.Join(append([]string{d, "usr", "bin"}, elem...)...))
	}
	return out
}

func CatalogPO(id string) (string, error) {
	id = strings.ToLower(strings.TrimSpace(id))
	id = strings.ReplaceAll(id, "_", "-")
	if id == "" {
		return "", fmt.Errorf("empty language id")
	}
	if env := os.Getenv("FIRSTBOOT_LOCALE"); env != "" {
		if dirExists(env) {
			p, err := FirstExisting(
				filepath.Join(env, id+".po"),
				filepath.Join(env, id, "LC_MESSAGES", "firstboot.po"),
			)
			if err != nil {
				return "", fmt.Errorf("FIRSTBOOT_LOCALE: no catalog for %s", id)
			}
			return p, nil
		}
		return "", fmt.Errorf("FIRSTBOOT_LOCALE: %s not found", env)
	}
	exe := ExecutableDir()
	candidates := sharePath("locale", id+".po")
	candidates = append(candidates, sharePath("locale", id, "LC_MESSAGES", "firstboot.po")...)
	candidates = append(candidates, sharePath(id+".po")...)
	candidates = append(candidates,
		filepath.Join(exe, "locale", id+".po"),
		filepath.Join(exe, id+".po"),
		filepath.Join(exe, "data", id+".po"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "po", id+".po"))
	}
	return FirstExisting(candidates...)
}

func LanguagesJSON() (string, error) {
	if env := os.Getenv("FIRSTBOOT_LANGUAGES"); env != "" {
		if fileExists(env) {
			return env, nil
		}
		return "", fmt.Errorf("FIRSTBOOT_LANGUAGES: %s not found", env)
	}
	exe := ExecutableDir()
	candidates := sharePath("languages.json")
	candidates = append(candidates,
		filepath.Join(exe, "languages.json"),
		filepath.Join(exe, "data", "languages.json"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "po", "languages.json"))
	}
	return FirstExisting(candidates...)
}

func KeyboardsJSON() (string, error) {
	if env := os.Getenv("FIRSTBOOT_KEYBOARDS"); env != "" {
		if fileExists(env) {
			return env, nil
		}
		return "", fmt.Errorf("FIRSTBOOT_KEYBOARDS: %s not found", env)
	}
	exe := ExecutableDir()
	candidates := sharePath("keyboards.json")
	candidates = append(candidates,
		filepath.Join(exe, "keyboards.json"),
		filepath.Join(exe, "data", "keyboards.json"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "po", "keyboards.json"))
	}
	return FirstExisting(candidates...)
}

func OfficialCatalog() (string, error) {
	if env := os.Getenv("FIRSTBOOT_OFFICIAL_CATALOG"); env != "" {
		if fileExists(env) {
			return env, nil
		}
		return "", fmt.Errorf("FIRSTBOOT_OFFICIAL_CATALOG: %s not found", env)
	}
	exe := ExecutableDir()
	candidates := sharePath("official-catalog.json")
	candidates = append(candidates,
		filepath.Join(exe, "official-catalog.json"),
		filepath.Join(exe, "data", "official-catalog.json"),
		filepath.Join(exe, "embed", "official-catalog.json"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "schemas", "official-catalog.json"))
	}
	return FirstExisting(candidates...)
}

func GrubCFG() (string, error) {
	exe := ExecutableDir()
	candidates := sharePath("boot", "grub.cfg")
	candidates = append(candidates,
		filepath.Join(exe, "boot", "grub.cfg"),
		filepath.Join(exe, "data", "boot", "grub.cfg"),
		filepath.Join(exe, "embed", "boot", "grub.cfg"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "image", "grub.cfg"))
	}
	return FirstExisting(candidates...)
}

func EFIGrubCFG() (string, error) {
	exe := ExecutableDir()
	candidates := sharePath("boot", "efi-grub.cfg")
	candidates = append(candidates,
		filepath.Join(exe, "boot", "efi-grub.cfg"),
		filepath.Join(exe, "data", "boot", "efi-grub.cfg"),
		filepath.Join(exe, "embed", "boot", "efi-grub.cfg"),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "image", "efi-grub.cfg"))
	}
	return FirstExisting(candidates...)
}

func DefaultWallpaper(which string) (string, error) {
	var name, unsplash string
	switch which {
	case "dark":
		name = "dark.jpg"
		unsplash = "annie-spratt-nJGaLopCqJk-unsplash.jpg"
	case "light":
		name = "light.jpg"
		unsplash = "ands-mahardika--MRPyzpWsh0-unsplash.jpg"
	default:
		return "", fmt.Errorf("wallpaper must be dark or light")
	}
	exe := ExecutableDir()
	candidates := sharePath("wallpapers", name)
	candidates = append(candidates,
		filepath.Join(exe, "wallpapers", name),
		filepath.Join(exe, "data", "wallpapers", name),
		filepath.Join(exe, "embed", "wallpapers", name),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates,
			filepath.Join(repo, "docs", "assets", "Wallpaper", unsplash),
		)
	}
	return FirstExisting(candidates...)
}

func DistroLogo(id string) string {
	name := id + ".png"
	exe := ExecutableDir()
	candidates := sharePath("logos", name)
	candidates = append(candidates,
		filepath.Join(exe, "logos", name),
		filepath.Join(exe, "data", "logos", name),
		filepath.Join(exe, "embed", "logos", name),
	)
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "docs", "assets", "distros", name))
	}
	p, err := FirstExisting(candidates...)
	if err != nil {
		return ""
	}
	return p
}

func AppIcon() string {
	exe := ExecutableDir()
	candidates := sharePath("icon.png")
	candidates = append(candidates,
		filepath.Join(exe, "icon.png"),
		filepath.Join(exe, "data", "icon.png"),
		filepath.Join(exe, "embed", "icon.png"),
	)
	if d := AppDir(); d != "" {
		candidates = append(candidates, filepath.Join(d, "firstboot-creator.png"))
	}
	if repo, err := RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "docs", "Logo", "First Boot Linux.png"))
	}
	p, err := FirstExisting(candidates...)
	if err != nil {
		return ""
	}
	return p
}

func CacheDir() string {
	if env := os.Getenv("FIRSTBOOT_CACHE"); env != "" {
		return env
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", "images")
	}
	return filepath.Join(home, ".cache", "firstboot", "images")
}

func DirExists(path string) bool  { return dirExists(path) }
func FileExists(path string) bool { return fileExists(path) }
