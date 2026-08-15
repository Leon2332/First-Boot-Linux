package passwd

import (
	"crypto/rand"
	"fmt"
	"io"
	"strings"

	"github.com/GehirnInc/crypt/sha512_crypt"
)

const alphabet = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

func Hash(password string) (string, error) {
	if password == "" {
		return "", fmt.Errorf("password is empty")
	}
	if strings.ContainsAny(password, "\n\r") {
		return "", fmt.Errorf("password cannot contain newlines")
	}
	salt, err := randomSalt(16)
	if err != nil {
		return "", err
	}
	c := sha512_crypt.New()
	out, err := c.Generate([]byte(password), []byte("$6$"+salt))
	if err != nil {
		return "", err
	}
	if !Valid(out) {
		return "", fmt.Errorf("generated hash is not SHA-512 crypt")
	}
	return out, nil
}

func Valid(hash string) bool {
	if !strings.HasPrefix(hash, "$6$") {
		return false
	}
	if len(hash) < 80 || len(hash) > 200 {
		return false
	}
	for _, c := range hash {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '/' || c == '$' {
			continue
		}
		return false
	}
	return true
}

func randomSalt(n int) (string, error) {
	buf := make([]byte, n)
	if _, err := io.ReadFull(rand.Reader, buf); err != nil {
		return "", err
	}
	out := make([]byte, n)
	for i, b := range buf {
		out[i] = alphabet[int(b)%len(alphabet)]
	}
	return string(out), nil
}
