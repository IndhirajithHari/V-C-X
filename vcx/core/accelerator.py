"""Hardware and Native C Accelerator for VCX.

Provides dynamic binding to native C runtimes (libc and OpenSSL libcrypto)
via ctypes, with transparent, zero-dependency pure-Python fallback.
"""

from __future__ import annotations
import ctypes
import ctypes.util
import hashlib
from typing import Any, Dict, List, Optional, Tuple


class _NativeBackend:
    """Manages low-level bindings to system C libraries."""

    def __init__(self):
        self.has_c_runtime = False
        self.has_crypto_accel = False
        self._libc = None
        self._libcrypto = None
        self._evp_sha256 = None
        self._evp_ctx_new = None
        self._evp_ctx_free = None
        self._evp_digest_init = None
        self._evp_digest_update = None
        self._evp_digest_final = None

        self._init_libc()
        self._init_libcrypto()

    def _init_libc(self) -> None:
        try:
            libc_path = ctypes.util.find_library("c")
            if libc_path:
                self._libc = ctypes.CDLL(libc_path)
                self._libc.memchr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
                self._libc.memchr.restype = ctypes.c_void_p
                self.has_c_runtime = True
        except Exception:
            self._libc = None
            self.has_c_runtime = False

    def _init_libcrypto(self) -> None:
        try:
            crypto_path = ctypes.util.find_library("crypto")
            if crypto_path:
                self._libcrypto = ctypes.CDLL(crypto_path)
                self._evp_sha256 = self._libcrypto.EVP_sha256
                self._evp_sha256.restype = ctypes.c_void_p

                self._evp_ctx_new = self._libcrypto.EVP_MD_CTX_new
                self._evp_ctx_new.restype = ctypes.c_void_p

                self._evp_ctx_free = self._libcrypto.EVP_MD_CTX_free
                self._evp_ctx_free.argtypes = [ctypes.c_void_p]

                self._evp_digest_init = self._libcrypto.EVP_DigestInit_ex
                self._evp_digest_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                self._evp_digest_init.restype = ctypes.c_int

                self._evp_digest_update = self._libcrypto.EVP_DigestUpdate
                self._evp_digest_update.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
                self._evp_digest_update.restype = ctypes.c_int

                self._evp_digest_final = self._libcrypto.EVP_DigestFinal_ex
                self._evp_digest_final.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint)]
                self._evp_digest_final.restype = ctypes.c_int

                self.has_crypto_accel = True
        except Exception:
            self._libcrypto = None
            self.has_crypto_accel = False


_BACKEND = _NativeBackend()


def get_accelerator_status() -> Dict[str, Any]:
    """Return runtime diagnostic metadata for native acceleration."""
    return {
        "backend": "native_c" if _BACKEND.has_c_runtime else "pure_python",
        "has_c_runtime": _BACKEND.has_c_runtime,
        "has_crypto_accel": _BACKEND.has_crypto_accel,
        "simd_memchr": _BACKEND.has_c_runtime,
    }


def fast_sha256(data: bytes) -> str:
    """Compute SHA-256 digest with hardware crypto acceleration if available."""
    if _BACKEND.has_crypto_accel:
        try:
            ctx = _BACKEND._evp_ctx_new()
            if ctx:
                _BACKEND._evp_digest_init(ctx, _BACKEND._evp_sha256(), None)
                _BACKEND._evp_digest_update(ctx, data, len(data))
                out_buf = ctypes.create_string_buffer(32)
                out_len = ctypes.c_uint()
                _BACKEND._evp_digest_final(ctx, out_buf, ctypes.byref(out_len))
                _BACKEND._evp_ctx_free(ctx)
                return out_buf.raw.hex()
        except Exception:
            pass
    return hashlib.sha256(data).hexdigest()


def fast_find_boundary(data: bytes, target_byte: int, start: int, end: int) -> int:
    """Find next matching byte offset using C memchr or Python bytes.find."""
    if start >= end or start >= len(data):
        return -1

    if _BACKEND.has_c_runtime and _BACKEND._libc:
        try:
            length = min(end, len(data)) - start
            base_ptr = ctypes.cast(ctypes.c_char_p(data[start:start + length]), ctypes.c_void_p).value
            res_ptr = _BACKEND._libc.memchr(base_ptr, target_byte, length)
            if res_ptr:
                return start + (res_ptr - base_ptr)
            return -1
        except Exception:
            pass

    return data.find(bytes([target_byte]), start, end)


def fast_cdc_chunks(
    data: bytes, min_chunk: int = 16384, max_chunk: int = 65536
) -> List[Tuple[int, int, str]]:
    """High-throughput Content-Defined Chunking using hardware boundary cuts."""
    if not data:
        return []

    chunks: List[Tuple[int, int, str]] = []
    pos = 0
    n = len(data)

    while pos < n:
        limit = min(pos + max_chunk, n)
        target = pos + min_chunk
        if target >= n:
            chunk_slice = data[pos:n]
            chunks.append((pos, n - pos, fast_sha256(chunk_slice)))
            break

        p = fast_find_boundary(data, 0, target, limit)
        cut = (p + 1) if p != -1 else limit

        chunk_slice = data[pos:cut]
        chunks.append((pos, cut - pos, fast_sha256(chunk_slice)))
        pos = cut

    return chunks
