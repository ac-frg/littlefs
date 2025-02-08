/*
 * lfs util functions
 *
 * Copyright (c) 2022, The littlefs authors.
 * Copyright (c) 2017, Arm Limited. All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */
#include "lfs_util.h"

// Only compile if user does not provide custom config
#ifndef LFS_CONFIG

// Need lfs.h for error codes
// TODO should we actually move the error codes to lfs_util.h?
#include "lfs.h"


// Convert to/from leb128 encoding
ssize_t lfs_toleb128(uint32_t word, void *buffer, size_t size) {
    uint8_t *data = buffer;

    for (size_t i = 0; i < size; i++) {
        uint8_t dat = word & 0x7f;
        word >>= 7;
        if (word != 0) {
            data[i] = dat | 0x80;
        } else {
            data[i] = dat | 0x00;
            return i+1;
        }
    }

    // buffer overflow?
    LFS_UNREACHABLE();
}

ssize_t lfs_fromleb128(uint32_t *word, const void *buffer, size_t size) {
    const uint8_t *data = buffer;

    int32_t word_ = 0;
    for (size_t i = 0; i < size; i++) {
        int32_t dat = data[i];
        word_ |= (dat & 0x7f) << 7*i;
        if (!(dat & 0x80)) {
            // did we overflow?
            if ((word_ >> 7*i) != dat) {
                return LFS_ERR_CORRUPT;
            }

            *word = word_;
            return i+1;
        }
    }

    // truncated?
    return LFS_ERR_CORRUPT;
}


//// Software CRC implementation with small lookup table
//uint32_t lfs_crc(uint32_t crc, const void *buffer, size_t size) {
//    static const uint32_t rtable[16] = {
//        0x00000000, 0x1db71064, 0x3b6e20c8, 0x26d930ac,
//        0x76dc4190, 0x6b6b51f4, 0x4db26158, 0x5005713c,
//        0xedb88320, 0xf00f9344, 0xd6d6a3e8, 0xcb61b38c,
//        0x9b64c2b0, 0x86d3d2d4, 0xa00ae278, 0xbdbdf21c,
//    };
//
//    const uint8_t *data = buffer;
//
//    for (size_t i = 0; i < size; i++) {
//        crc = (crc >> 4) ^ rtable[(crc ^ (data[i] >> 0)) & 0xf];
//        crc = (crc >> 4) ^ rtable[(crc ^ (data[i] >> 4)) & 0xf];
//    }
//
//    return crc;
//}


// crc32c tables (see lfs_crc32c for more info)
#if !defined(LFS_FASTER_CRC32C)
static const uint32_t lfs_crc32c_table[16] = {
    0x00000000, 0x105ec76f, 0x20bd8ede, 0x30e349b1,
    0x417b1dbc, 0x5125dad3, 0x61c69362, 0x7198540d,
    0x82f63b78, 0x92a8fc17, 0xa24bb5a6, 0xb21572c9,
    0xc38d26c4, 0xd3d3e1ab, 0xe330a81a, 0xf36e6f75,
};

#else
static const uint32_t lfs_crc32c_table[256] = {
    0x00000000, 0xf26b8303, 0xe13b70f7, 0x1350f3f4,
    0xc79a971f, 0x35f1141c, 0x26a1e7e8, 0xd4ca64eb,
    0x8ad958cf, 0x78b2dbcc, 0x6be22838, 0x9989ab3b,
    0x4d43cfd0, 0xbf284cd3, 0xac78bf27, 0x5e133c24,
    0x105ec76f, 0xe235446c, 0xf165b798, 0x030e349b,
    0xd7c45070, 0x25afd373, 0x36ff2087, 0xc494a384,
    0x9a879fa0, 0x68ec1ca3, 0x7bbcef57, 0x89d76c54,
    0x5d1d08bf, 0xaf768bbc, 0xbc267848, 0x4e4dfb4b,
    0x20bd8ede, 0xd2d60ddd, 0xc186fe29, 0x33ed7d2a,
    0xe72719c1, 0x154c9ac2, 0x061c6936, 0xf477ea35,
    0xaa64d611, 0x580f5512, 0x4b5fa6e6, 0xb93425e5,
    0x6dfe410e, 0x9f95c20d, 0x8cc531f9, 0x7eaeb2fa,
    0x30e349b1, 0xc288cab2, 0xd1d83946, 0x23b3ba45,
    0xf779deae, 0x05125dad, 0x1642ae59, 0xe4292d5a,
    0xba3a117e, 0x4851927d, 0x5b016189, 0xa96ae28a,
    0x7da08661, 0x8fcb0562, 0x9c9bf696, 0x6ef07595,
    0x417b1dbc, 0xb3109ebf, 0xa0406d4b, 0x522bee48,
    0x86e18aa3, 0x748a09a0, 0x67dafa54, 0x95b17957,
    0xcba24573, 0x39c9c670, 0x2a993584, 0xd8f2b687,
    0x0c38d26c, 0xfe53516f, 0xed03a29b, 0x1f682198,
    0x5125dad3, 0xa34e59d0, 0xb01eaa24, 0x42752927,
    0x96bf4dcc, 0x64d4cecf, 0x77843d3b, 0x85efbe38,
    0xdbfc821c, 0x2997011f, 0x3ac7f2eb, 0xc8ac71e8,
    0x1c661503, 0xee0d9600, 0xfd5d65f4, 0x0f36e6f7,
    0x61c69362, 0x93ad1061, 0x80fde395, 0x72966096,
    0xa65c047d, 0x5437877e, 0x4767748a, 0xb50cf789,
    0xeb1fcbad, 0x197448ae, 0x0a24bb5a, 0xf84f3859,
    0x2c855cb2, 0xdeeedfb1, 0xcdbe2c45, 0x3fd5af46,
    0x7198540d, 0x83f3d70e, 0x90a324fa, 0x62c8a7f9,
    0xb602c312, 0x44694011, 0x5739b3e5, 0xa55230e6,
    0xfb410cc2, 0x092a8fc1, 0x1a7a7c35, 0xe811ff36,
    0x3cdb9bdd, 0xceb018de, 0xdde0eb2a, 0x2f8b6829,
    0x82f63b78, 0x709db87b, 0x63cd4b8f, 0x91a6c88c,
    0x456cac67, 0xb7072f64, 0xa457dc90, 0x563c5f93,
    0x082f63b7, 0xfa44e0b4, 0xe9141340, 0x1b7f9043,
    0xcfb5f4a8, 0x3dde77ab, 0x2e8e845f, 0xdce5075c,
    0x92a8fc17, 0x60c37f14, 0x73938ce0, 0x81f80fe3,
    0x55326b08, 0xa759e80b, 0xb4091bff, 0x466298fc,
    0x1871a4d8, 0xea1a27db, 0xf94ad42f, 0x0b21572c,
    0xdfeb33c7, 0x2d80b0c4, 0x3ed04330, 0xccbbc033,
    0xa24bb5a6, 0x502036a5, 0x4370c551, 0xb11b4652,
    0x65d122b9, 0x97baa1ba, 0x84ea524e, 0x7681d14d,
    0x2892ed69, 0xdaf96e6a, 0xc9a99d9e, 0x3bc21e9d,
    0xef087a76, 0x1d63f975, 0x0e330a81, 0xfc588982,
    0xb21572c9, 0x407ef1ca, 0x532e023e, 0xa145813d,
    0x758fe5d6, 0x87e466d5, 0x94b49521, 0x66df1622,
    0x38cc2a06, 0xcaa7a905, 0xd9f75af1, 0x2b9cd9f2,
    0xff56bd19, 0x0d3d3e1a, 0x1e6dcdee, 0xec064eed,
    0xc38d26c4, 0x31e6a5c7, 0x22b65633, 0xd0ddd530,
    0x0417b1db, 0xf67c32d8, 0xe52cc12c, 0x1747422f,
    0x49547e0b, 0xbb3ffd08, 0xa86f0efc, 0x5a048dff,
    0x8ecee914, 0x7ca56a17, 0x6ff599e3, 0x9d9e1ae0,
    0xd3d3e1ab, 0x21b862a8, 0x32e8915c, 0xc083125f,
    0x144976b4, 0xe622f5b7, 0xf5720643, 0x07198540,
    0x590ab964, 0xab613a67, 0xb831c993, 0x4a5a4a90,
    0x9e902e7b, 0x6cfbad78, 0x7fab5e8c, 0x8dc0dd8f,
    0xe330a81a, 0x115b2b19, 0x020bd8ed, 0xf0605bee,
    0x24aa3f05, 0xd6c1bc06, 0xc5914ff2, 0x37faccf1,
    0x69e9f0d5, 0x9b8273d6, 0x88d28022, 0x7ab90321,
    0xae7367ca, 0x5c18e4c9, 0x4f48173d, 0xbd23943e,
    0xf36e6f75, 0x0105ec76, 0x12551f82, 0xe03e9c81,
    0x34f4f86a, 0xc69f7b69, 0xd5cf889d, 0x27a40b9e,
    0x79b737ba, 0x8bdcb4b9, 0x988c474d, 0x6ae7c44e,
    0xbe2da0a5, 0x4c4623a6, 0x5f16d052, 0xad7d5351,
};
#endif


// Calculate crc32c incrementally
uint32_t lfs_crc32c(uint32_t crc, const void *buffer, size_t size) {
    // init with 0xffffffff so prefixed zeros affect the crc
    const uint8_t *data = buffer;
    crc ^= 0xffffffff;

    // A couple crc32c implementations to choose from.
    //
    // The default, "small-table" implementation offers a decent performance
    // without much additional code-size, reasonable for microcontrollers. For
    // anything larger where you really don't care about an extra 1KiB of code
    // the "big-table" implementation is probably better.
    //
    // Some quick measurements with GCC 11 using -Os -mcpu=cortex-m55, with
    // instruction counts from QEMU and an input size of 4KiB. Note these are
    // not cycle-accurate:
    //
    //                code   stack     ins   ld/st  branch
    // naive            48      12  221192    4099   36865
    // small-table     124      12   49160   12291    4097
    // big-table      1064       8   32776    8195    4097
    //
    #if defined(LFS_SMALLER_CRC32C)
    for (size_t i = 0; i < size; i++) {
        crc = crc ^ data[i];
        for (size_t j = 0; j < 8; j++) {
            crc = (crc >> 1) ^ ((crc & 1) ? 0x82f63b78 : 0);
        }
    }

    #elif !defined(LFS_FASTER_CRC32C)
    for (size_t i = 0; i < size; i++) {
        crc = (crc >> 4) ^ lfs_crc32c_table[0xf & (crc ^ (data[i] >> 0))];
        crc = (crc >> 4) ^ lfs_crc32c_table[0xf & (crc ^ (data[i] >> 4))];
    }

    #else
    for (size_t i = 0; i < size; i++) {
        crc = (crc >> 8) ^ lfs_crc32c_table[0xff & (crc ^ data[i])];
    }
    #endif

    // fini with 0xffffffff to cancel out init when called incrementally
    crc ^= 0xffffffff;
    return crc;
}

// Multiply two crc32cs in the crc32c ring
uint32_t lfs_crc32c_mul(uint32_t a, uint32_t b) {
    // Multiplication in a crc32c ring involves polynomial
    // multiplication modulo the crc32c polynomial to keep things
    // finite:
    //
    // r = a * b mod P
    //
    // Note because our crc32c is not irreducible, this does not give
    // us a finite-field, i.e. division is undefined. Still,
    // multiplication has useful properties.

    // This gets a bit funky because crc32cs are little-endian, but
    // fortunately pmul is symmetric. Unfortunately the result is
    // 31-bits large, so we need to shift by 1.
    uint64_t r = lfs_pmul(a, b) << 1;

    // We can accelerate our module with crc32c tables if present, these
    // loops may look familiar.
    #if defined(LFS_SMALLER_CRC32C)
    for (int i = 0; i < 32; i++) {
        r = (r >> 1) ^ ((r & 1) ? 0x82f63b78 : 0);
    }

    #elif !defined(LFS_FASTER_CRC32C)
    for (int i = 0; i < 8; i++) {
        r = (r >> 4) ^ lfs_crc32c_table[0xf & r];
    }

    #else
    for (int i = 0; i < 4; i++) {
        r = (r >> 8) ^ lfs_crc32c_table[0xff & r];
    }
    #endif

    return (uint32_t)r;
}

#endif
