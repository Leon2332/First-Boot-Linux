package passwd

import (
	"strings"
	"testing"
)

func TestHash(t *testing.T) {
	h, err := Hash("shop-secret-1")
	if err != nil {
		t.Fatal(err)
	}
	if !Valid(h) {
		t.Fatalf("invalid hash %s", h)
	}
	if !strings.HasPrefix(h, "$6$") {
		t.Fatalf("want sha512 crypt, got %s", h)
	}
	h2, err := Hash("shop-secret-1")
	if err != nil {
		t.Fatal(err)
	}
	if h == h2 {
		t.Fatalf("salts should differ")
	}
	if _, err := Hash(""); err == nil {
		t.Fatalf("empty password")
	}
	if Valid("not-a-hash") || Valid("$6$short") {
		t.Fatalf("accepted junk")
	}
}
