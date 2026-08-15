package cache

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
)

type ProgressFunc func(filename string, got, total int64)

type Store struct {
	Dir    string
	Client *http.Client
}

func New(dir string) *Store {
	if dir == "" {
		dir = defaultDir()
	}
	return &Store{
		Dir: dir,
		Client: &http.Client{
			Timeout: 0,
		},
	}
}

func defaultDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", "images")
	}
	return filepath.Join(home, ".cache", "firstboot", "images")
}

func (s *Store) Path(filename string) string {
	return filepath.Join(s.Dir, filename)
}

func (s *Store) Status(ed catalog.Edition) (cached bool, err error) {
	if !ed.Pinned() {
		return false, fmt.Errorf("%s is not pinned", ed.Filename)
	}
	p := s.Path(ed.Filename)
	st, err := os.Stat(p)
	if err != nil {
		return false, nil
	}
	if st.Size() != *ed.SizeBytes {
		return false, nil
	}
	sum, err := HashFile(p)
	if err != nil {
		return false, err
	}
	return sum == *ed.SHA256, nil
}

func (s *Store) Ensure(ctx context.Context, ed catalog.Edition, progress ProgressFunc) (string, error) {
	if !ed.Pinned() {
		return "", fmt.Errorf("%s: pin url, sha256, and size_bytes before download", ed.Filename)
	}
	if err := os.MkdirAll(s.Dir, 0o755); err != nil {
		return "", err
	}
	dest := s.Path(ed.Filename)
	if ok, err := s.Status(ed); err != nil {
		return "", err
	} else if ok {
		if progress != nil {
			progress(ed.Filename, *ed.SizeBytes, *ed.SizeBytes)
		}
		return dest, nil
	}
	if err := s.download(ctx, *ed.URL, dest, *ed.SHA256, *ed.SizeBytes, ed.Filename, progress); err != nil {
		return "", err
	}
	return dest, nil
}

func (s *Store) download(ctx context.Context, url, dest, wantSHA string, wantSize int64, name string, progress ProgressFunc) error {
	part := dest + ".part"
	var have int64
	if st, err := os.Stat(part); err == nil {
		have = st.Size()
		if have > wantSize {
			_ = os.Remove(part)
			have = 0
		}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "FirstBootCreator/1.0")
	if have > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", have))
	}

	resp, err := s.Client.Do(req)
	if err != nil {
		return fmt.Errorf("download %s: %w", name, err)
	}
	defer resp.Body.Close()

	var flags int
	switch resp.StatusCode {
	case http.StatusPartialContent:
		flags = os.O_WRONLY | os.O_APPEND
	case http.StatusOK:
		have = 0
		flags = os.O_WRONLY | os.O_CREATE | os.O_TRUNC
	default:
		return fmt.Errorf("download %s: HTTP %s", name, resp.Status)
	}

	out, err := os.OpenFile(part, flags, 0o644)
	if err != nil {
		return err
	}
	defer out.Close()

	hash := sha256.New()
	if have > 0 {
		prev, err := os.Open(part)
		if err != nil {
			return err
		}
		if _, err := io.Copy(hash, prev); err != nil {
			prev.Close()
			return err
		}
		prev.Close()
	}

	buf := make([]byte, 256*1024)
	got := have
	if progress != nil {
		progress(name, got, wantSize)
	}
	last := time.Now()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, err := out.Write(buf[:n]); err != nil {
				return err
			}
			_, _ = hash.Write(buf[:n])
			got += int64(n)
			if progress != nil && time.Since(last) > 80*time.Millisecond {
				progress(name, got, wantSize)
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
		progress(name, got, wantSize)
	}
	if err := out.Close(); err != nil {
		return err
	}
	if got != wantSize {
		return fmt.Errorf("%s: got %d bytes, expected %d", name, got, wantSize)
	}
	sum := hex.EncodeToString(hash.Sum(nil))
	if sum != wantSHA {
		_ = os.Remove(part)
		return fmt.Errorf("%s: sha256 mismatch", name)
	}
	if err := os.Rename(part, dest); err != nil {
		return err
	}
	return nil
}

func HashFile(path string) (string, error) {
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
