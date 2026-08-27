package compose

import (
	"context"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/cache"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/passwd"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/seedpath"
	diskfs "github.com/diskfs/go-diskfs"
	"github.com/diskfs/go-diskfs/disk"
	"github.com/diskfs/go-diskfs/filesystem"
)

var (
	ESPMiB       = 512
	SYSMiB       = 2048
	minDataBytes int64 = 256 << 20
)

type ProgressFunc func(stage string, got, total int64)

type Request struct {
	Retailer catalog.Retailer
	Shop     *catalog.Shop
	Official *catalog.Official
	Seed     *seedpath.Seed
	Cache    *cache.Store
	Out      string
	Password string
	WorkDir  string
	Progress ProgressFunc
}

type Estimate struct {
	ESPBytes    int64
	SYSBytes    int64
	DataBytes   int64
	ImageBytes  int64
	ISOBytes    int64
	StickGB     int
	DiskGB      int
	NeedHuman   string
	Summary     string
}

func Plan(seed *seedpath.Seed, shop *catalog.Shop) Estimate {
	esp := int64(ESPMiB) << 20
	sysNeed := seed.CasperBytes() + 32<<20
	sys := int64(SYSMiB) << 20
	if sysNeed+64<<20 > sys {
		sys = alignMiB(sysNeed + 64<<20)
	}
	iso := shop.LocalBytes()
	data := iso + wallpaperBudget() + 8<<20
	data += data/10 + 64<<20
	if data < minDataBytes {
		data = minDataBytes
	}
	data = alignMiB(data)
	image := int64(2<<20) + esp + sys + data
	image = alignMiB(image)
	e := Estimate{
		ESPBytes:   esp,
		SYSBytes:   sys,
		DataBytes:  data,
		ImageBytes: image,
		ISOBytes:   iso,
		StickGB:    catalog.StickSuggestion(image),
		DiskGB:     catalog.DiskSuggestion(image, shop.LargestLocal()),
		NeedHuman:  catalog.FormatBytes(image),
	}
	e.Summary = fmt.Sprintf(
		"This set needs %s on the stick. Use a %d GB USB. The PC you install onto should have at least %d GB so the chosen OS can unpack.",
		e.NeedHuman, e.StickGB, e.DiskGB,
	)
	return e
}

func wallpaperBudget() int64 { return 16 << 20 }

func alignMiB(n int64) int64 {
	const m = 1 << 20
	return (n + m - 1) / m * m
}

func Write(ctx context.Context, req Request) error {
	if req.Shop == nil || req.Official == nil || req.Seed == nil {
		return fmt.Errorf("compose: missing seed or catalog")
	}
	if err := catalog.ValidateRetailer(req.Retailer); err != nil {
		return err
	}
	if req.Out == "" {
		return fmt.Errorf("compose: no output path")
	}
	if req.Cache == nil {
		req.Cache = cache.New("")
	}

	locals := req.Shop.LocalEditions()
	if len(locals) == 0 {
		return fmt.Errorf("compose: nothing to stage")
	}

	isoPaths := map[string]string{}
	for _, ed := range locals {
		base := filepath.Base(ed.File)
		offEd := officialEdition(req.Official, base)
		if offEd == nil {
			return fmt.Errorf("compose: %s not in official catalog", base)
		}
		report(req, "download "+base, 0, ed.SizeBytes)
		p, err := req.Cache.Ensure(ctx, *offEd, func(name string, got, total int64) {
			report(req, "download "+name, got, total)
		})
		if err != nil {
			return err
		}
		isoPaths[ed.File] = p
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	est := Plan(req.Seed, req.Shop)
	work := req.WorkDir
	if work == "" {
		work = req.Out + ".work"
	}
	if err := os.RemoveAll(work); err != nil {
		return err
	}
	if err := os.MkdirAll(work, 0o755); err != nil {
		return err
	}
	defer os.RemoveAll(work)

	sysUUID, err := newSysUUID()
	if err != nil {
		return err
	}
	sysTree := filepath.Join(work, "sys")
	dataTree := filepath.Join(work, "data")
	if err := buildSYS(req, sysTree, sysUUID); err != nil {
		return err
	}
	if err := buildDATA(req, dataTree, isoPaths); err != nil {
		return err
	}

	report(req, "format FBL-SYS", 0, 1)
	sysImg := filepath.Join(work, "sys.ext4")
	if err := makeExt4(sysImg, est.SYSBytes, "FBL-SYS", sysTree, sysUUID); err != nil {
		return err
	}
	report(req, "format FBL-DATA", 0, 1)
	dataImg := filepath.Join(work, "data.ext4")
	if err := makeExt4(dataImg, est.DataBytes, "FBL-DATA", dataTree, ""); err != nil {
		return err
	}
	report(req, "format FBL-ESP", 0, 1)
	espImg := filepath.Join(work, "esp.fat")
	if err := makeESP(espImg, est.ESPBytes, req.Seed, sysUUID); err != nil {
		return err
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	report(req, "assemble disk", 0, est.ESPBytes+est.SYSBytes+est.DataBytes)
	if err := os.MkdirAll(filepath.Dir(req.Out), 0o755); err != nil && !os.IsExist(err) {
		return err
	}
	tmpOut := req.Out + ".partial"
	_ = os.Remove(tmpOut)
	if err := assemble(ctx, tmpOut, est, espImg, sysImg, dataImg, req.Progress); err != nil {
		_ = os.Remove(tmpOut)
		return err
	}
	if err := os.Rename(tmpOut, req.Out); err != nil {
		return err
	}
	report(req, "done", est.ImageBytes, est.ImageBytes)
	return nil
}

func officialEdition(off *catalog.Official, filename string) *catalog.Edition {
	for i := range off.Distros {
		for j := range off.Distros[i].Editions {
			if off.Distros[i].Editions[j].Filename == filename {
				return &off.Distros[i].Editions[j]
			}
		}
	}
	return nil
}

func buildSYS(req Request, root, sysUUID string) error {
	s := req.Seed
	for _, d := range []string{
		filepath.Join(root, ".disk"),
		filepath.Join(root, "casper"),
		filepath.Join(root, "boot", "grub"),
		filepath.Join(root, "firstboot"),
	} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	if err := os.WriteFile(filepath.Join(root, ".disk", "info"), []byte("First Boot Linux "+s.Version+"\n"), 0o644); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(root, ".disk", "ubuntu_dist_channel"), []byte("firstboot\n"), 0o644); err != nil {
		return err
	}
	grub, err := assets.GrubCFG()
	if err != nil {
		return err
	}
	if err := writeFilled(grub, filepath.Join(root, "boot", "grub", "grub.cfg"), sysUUID); err != nil {
		return err
	}
	if err := linkOrCopy(s.Vmlinuz, filepath.Join(root, "casper", "vmlinuz")); err != nil {
		return err
	}
	if err := linkOrCopy(s.Initrd, filepath.Join(root, "casper", "initrd")); err != nil {
		return err
	}
	if err := linkOrCopy(s.Squashfs, filepath.Join(root, "casper", "filesystem.squashfs")); err != nil {
		return err
	}
	if assets.FileExists(s.Size) {
		if err := copyFile(s.Size, filepath.Join(root, "casper", "filesystem.size"), 0o644); err != nil {
			return err
		}
	}
	if assets.FileExists(s.Manifest) {
		if err := copyFile(s.Manifest, filepath.Join(root, "casper", "filesystem.manifest"), 0o644); err != nil {
			return err
		}
	}
	if err := os.WriteFile(filepath.Join(root, "casper", "filesystem.manifest-remove"), nil, 0o644); err != nil {
		return err
	}
	if req.Password != "" {
		hash, err := passwd.Hash(req.Password)
		if err != nil {
			return err
		}
		p := filepath.Join(root, "firstboot", "live-user.hash")
		if err := os.WriteFile(p, []byte(hash+"\n"), 0o600); err != nil {
			return err
		}
	}
	if err := writeSums(root, "SHA256SUMS", sha256sum); err != nil {
		return err
	}
	return writeSums(root, "md5sum.txt", md5sum)
}

func buildDATA(req Request, root string, isos map[string]string) error {
	for _, d := range []string{
		filepath.Join(root, "wallpapers"),
		filepath.Join(root, "images"),
	} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	if err := os.WriteFile(filepath.Join(root, "retailer.conf"), []byte(catalog.RetailerFile(req.Retailer)), 0o644); err != nil {
		return err
	}
	lang := strings.TrimSpace(req.Retailer.Language)
	if lang == "" {
		lang = "en"
	}
	if err := os.WriteFile(filepath.Join(root, "language"), []byte(lang+"\n"), 0o644); err != nil {
		return err
	}
	tz := catalog.NormalizeRetailerTimezone(req.Retailer.Timezone)
	if err := os.WriteFile(filepath.Join(root, "timezone"), []byte(tz+"\n"), 0o644); err != nil {
		return err
	}
	shopJSON, err := marshalShop(req.Shop)
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(root, "catalog.json"), shopJSON, 0o644); err != nil {
		return err
	}
	if err := copyAsJPEG(req.Retailer.WallpaperDark, filepath.Join(root, "wallpapers", "dark.jpg")); err != nil {
		return err
	}
	if err := copyAsJPEG(req.Retailer.WallpaperLight, filepath.Join(root, "wallpapers", "light.jpg")); err != nil {
		return err
	}
	for _, ed := range req.Shop.LocalEditions() {
		src := isos[ed.File]
		if src == "" {
			return fmt.Errorf("missing cached %s", ed.File)
		}
		dest := filepath.Join(root, filepath.FromSlash(ed.File))
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return err
		}
		if err := linkOrCopy(src, dest); err != nil {
			return err
		}
		sum, err := cache.HashFile(dest)
		if err != nil {
			return err
		}
		if sum != ed.SHA256 {
			return fmt.Errorf("%s: sha256 mismatch after copy", ed.File)
		}
	}
	return writePayloadChecksums(root)
}

func marshalShop(s *catalog.Shop) ([]byte, error) {
	// encoding/json with indent; keep catalog key even when empty.
	type wire struct {
		SchemaVersion int                 `json:"schema_version"`
		Recommended   []catalog.ShopDistro `json:"recommended"`
		Catalog       []catalog.ShopDistro `json:"catalog"`
	}
	w := wire{SchemaVersion: s.SchemaVersion, Recommended: s.Recommended, Catalog: s.Catalog}
	if w.Recommended == nil {
		w.Recommended = []catalog.ShopDistro{}
	}
	if w.Catalog == nil {
		w.Catalog = []catalog.ShopDistro{}
	}
	enc, err := json.MarshalIndent(w, "", "  ")
	if err != nil {
		return nil, err
	}
	enc = append(enc, '\n')
	return enc, nil
}

func copyAsJPEG(src, dest string) error {
	return copyFile(src, dest, 0o644)
}

func makeExt4(img string, size int64, label, tree, uuid string) error {
	if err := truncate(img, size); err != nil {
		return err
	}
	mke2fs, err := exec.LookPath("mke2fs")
	if err != nil {
		return fmt.Errorf("mke2fs not found (install e2fsprogs)")
	}
	args := []string{"-t", "ext4", "-F", "-q", "-L", label, "-m", "0"}
	if uuid != "" {
		args = append(args, "-U", uuid)
	}
	args = append(args, "-d", tree, img)
	cmd := exec.Command(mke2fs, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("mke2fs %s: %w\n%s", label, err, out)
	}
	return nil
}

func makeESP(img string, size int64, seed *seedpath.Seed, sysUUID string) error {
	_ = os.Remove(img)
	dev, err := diskfs.Create(img, size, diskfs.SectorSize512)
	if err != nil {
		return fmt.Errorf("esp create: %w", err)
	}
	defer dev.Close()
	fs, err := dev.CreateFilesystem(disk.FilesystemSpec{
		Partition:   0,
		FSType:      filesystem.TypeFat32,
		VolumeLabel: "FBL-ESP",
	})
	if err != nil {
		return fmt.Errorf("esp fat32: %w", err)
	}
	stubPath, err := assets.EFIGrubCFG()
	if err != nil {
		return err
	}
	stubBytes, err := os.ReadFile(stubPath)
	if err != nil {
		return err
	}
	stub := fillSysUUID(string(stubBytes), sysUUID)
	stubFile := filepath.Join(filepath.Dir(img), "efi-grub.filled.cfg")
	if err := os.WriteFile(stubFile, []byte(stub), 0o644); err != nil {
		return err
	}
	stub = stubFile
	type file struct {
		dest, src string
	}
	files := []file{
		{"/EFI/BOOT/BOOTX64.EFI", seed.EFI.BOOTX64},
		{"/EFI/BOOT/grubx64.efi", seed.EFI.GRUB},
		{"/EFI/BOOT/grub.cfg", stub},
		{"/EFI/firstboot/shimx64.efi", seed.EFI.Shim},
		{"/EFI/firstboot/grubx64.efi", seed.EFI.GRUB},
		{"/EFI/firstboot/grub.cfg", stub},
		{"/EFI/ubuntu/grub.cfg", stub},
	}
	if seed.EFI.MOK != "" {
		files = append(files, file{"/EFI/BOOT/mmx64.efi", seed.EFI.MOK})
	}
	for _, f := range files {
		if err := fatWrite(fs, f.dest, f.src); err != nil {
			return err
		}
	}
	return nil
}

func fatWrite(fs filesystem.FileSystem, dest, src string) error {
	dir := filepath.ToSlash(filepath.Dir(dest))
	if dir != "/" && dir != "." {
		if err := fs.Mkdir(dir); err != nil {
			// parent chain
			parts := strings.Split(strings.Trim(dir, "/"), "/")
			cur := ""
			for _, p := range parts {
				cur += "/" + p
				_ = fs.Mkdir(cur)
			}
		}
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := fs.OpenFile(dest, os.O_CREATE|os.O_RDWR|os.O_TRUNC)
	if err != nil {
		return fmt.Errorf("esp write %s: %w", dest, err)
	}
	defer out.Close()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return nil
}

func assemble(ctx context.Context, out string, est Estimate, esp, sys, data string, progress ProgressFunc) error {
	if err := truncate(out, est.ImageBytes); err != nil {
		return err
	}
	f, err := os.OpenFile(out, os.O_RDWR, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()

	espStart := uint64(gptFirstUsable)
	espSectors := uint64(est.ESPBytes / sectorSize)
	sysStart := espStart + espSectors
	sysSectors := uint64(est.SYSBytes / sectorSize)
	dataStart := sysStart + sysSectors
	dataSectors := uint64(est.DataBytes / sectorSize)
	dataEnd := dataStart + dataSectors - 1
	lastUsable := uint64(est.ImageBytes/sectorSize) - 34
	if dataEnd > lastUsable {
		return fmt.Errorf("partitions exceed image (%d > %d)", dataEnd, lastUsable)
	}

	parts := []gptPart{
		{Type: typeEFI, GUID: randomGUID(), Start: espStart, End: espStart + espSectors - 1, Name: "FBL-ESP"},
		{Type: typeLinux, GUID: randomGUID(), Start: sysStart, End: sysStart + sysSectors - 1, Name: "FBL-SYS"},
		{Type: typeLinux, GUID: randomGUID(), Start: dataStart, End: dataEnd, Name: "FBL-DATA"},
	}
	if err := writeGPT(f, est.ImageBytes, parts); err != nil {
		return err
	}
	all := est.ESPBytes + est.SYSBytes + est.DataBytes
	var copied int64
	if err := copyAt(ctx, f, int64(espStart)*sectorSize, esp, progress, "write ESP", copied, all); err != nil {
		return err
	}
	copied += est.ESPBytes
	if err := copyAt(ctx, f, int64(sysStart)*sectorSize, sys, progress, "write FBL-SYS", copied, all); err != nil {
		return err
	}
	copied += est.SYSBytes
	if err := copyAt(ctx, f, int64(dataStart)*sectorSize, data, progress, "write FBL-DATA", copied, all); err != nil {
		return err
	}
	return f.Sync()
}

func copyAt(ctx context.Context, dst *os.File, off int64, srcPath string, progress ProgressFunc, stage string, base, all int64) error {
	in, err := os.Open(srcPath)
	if err != nil {
		return err
	}
	defer in.Close()
	if _, err := dst.Seek(off, io.SeekStart); err != nil {
		return err
	}
	buf := make([]byte, 1024*1024)
	var got int64
	last := time.Now()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		n, readErr := in.Read(buf)
		if n > 0 {
			if _, err := dst.Write(buf[:n]); err != nil {
				return err
			}
			got += int64(n)
			if progress != nil && time.Since(last) > 100*time.Millisecond {
				progress(stage, base+got, all)
				last = time.Now()
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	if progress != nil {
		progress(stage, base+got, all)
	}
	return nil
}

func newSysUUID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:]), nil
}

func fillSysUUID(s, uuid string) string {
	return strings.ReplaceAll(s, "@SYS_UUID@", uuid)
}

func writeFilled(src, dest, uuid string) error {
	raw, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dest, []byte(fillSysUUID(string(raw), uuid)), 0o644)
}

func truncate(path string, size int64) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Truncate(size)
}

func linkOrCopy(src, dest string) error {
	_ = os.Remove(dest)
	if err := os.Link(src, dest); err == nil {
		return nil
	}
	return copyFile(src, dest, 0)
}

func copyFile(src, dest string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	st, err := in.Stat()
	if err != nil {
		return err
	}
	if mode == 0 {
		mode = st.Mode().Perm()
	}
	out, err := os.OpenFile(dest, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Chmod(mode); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

func writeSums(root, name string, sumFn func(string) (string, error)) error {
	var files []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		base := filepath.Base(rel)
		if base == "SHA256SUMS" || base == "md5sum.txt" {
			return nil
		}
		files = append(files, rel)
		return nil
	})
	if err != nil {
		return err
	}
	sort.Strings(files)
	var b strings.Builder
	for _, rel := range files {
		sum, err := sumFn(filepath.Join(root, rel))
		if err != nil {
			return err
		}
		fmt.Fprintf(&b, "%s  ./%s\n", sum, filepath.ToSlash(rel))
	}
	return os.WriteFile(filepath.Join(root, name), []byte(b.String()), 0o644)
}

func writePayloadChecksums(root string) error {
	var files []string
	add := func(rel string) {
		if assets.FileExists(filepath.Join(root, rel)) {
			files = append(files, rel)
		}
	}
	add("retailer.conf")
	add("catalog.json")
	_ = filepath.Walk(filepath.Join(root, "wallpapers"), func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		rel, _ := filepath.Rel(root, path)
		files = append(files, rel)
		return nil
	})
	_ = filepath.Walk(filepath.Join(root, "images"), func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		rel, _ := filepath.Rel(root, path)
		files = append(files, rel)
		return nil
	})
	sort.Strings(files)
	var b strings.Builder
	for _, rel := range files {
		sum, err := sha256sum(filepath.Join(root, rel))
		if err != nil {
			return err
		}
		fmt.Fprintf(&b, "%s  %s\n", sum, filepath.ToSlash(rel))
	}
	return os.WriteFile(filepath.Join(root, "checksums.sha256"), []byte(b.String()), 0o644)
}

func sha256sum(path string) (string, error) {
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

func md5sum(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func report(req Request, stage string, got, total int64) {
	if req.Progress != nil {
		req.Progress(stage, got, total)
	}
}
