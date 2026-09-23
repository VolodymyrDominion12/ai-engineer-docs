# bitsandbytes-foundation/bitsandbytes 0.50.0 released 2026-07-25T01:42:24Z

This release brings a new fused 4-bit GEMM for inference on CUDA and ROCm, faster CPU ops on x86-64 and ARM64, reduced host-side overhead, and a much improved Apple Silicon backend. We've also added Windows on ARM CPU support, ROCm builds for Windows, additional ROCm and CUDA build variants, and new optimizer support on CPU and Intel XPU.

## Highlights

### 🚀 New 4-bit GEMM kernels for inference (CUDA)
New fused 4-bit dequantize + GEMM kernels replace the old GEMV and `dequantize + F.linear` paths for small-to-medium batch sizes. 4-bit inference is up to 4x faster at batch sizes of 2 through 64 across Turing through Blackwell, with wins at batch size 1 in many cases too. Nested (double) quantization and bias are fused in as well, so nested quant sees an additional benefit. Kernel selection happens automatically at runtime based on shape, GPU architecture, and SM count. See #1949 for benchmarks and details.

### 🚀 Fused 4-bit SIMT GEMM on ROCm
The SIMT version of the new 4-bit GEMM has been ported to ROCm and wired into the same dispatch for small inference batches, validated on gfx1100, gfx1201, and gfx1151 (#1979).

### AMD ROCm improvements
Stability and performance improvements bring AMD ROCm support out of preview; it is now considered stable.
* ROCm wheels for Windows are now published for ROCm 7.2 and 7.14 (#1915, #2007).
* Added ROCm 7.14 and dropped the ROCm 6.2 and 6.3 builds (#2007).
* Expanded GPU target coverage to add RDNA2 consumer GPUs, additional RDNA3 and RDNA3.5 GPUs, and CDNA1 (gfx908) data center GPUs (#1886, #2007).

### Apple Silicon (MPS)
Apple Silicon support is improved. The MPS backend added optimized Metal kernels from the Hub (#1875) and was substantially improved (#1960, #1983, #1994) so that all 4-bit and LLM.int8() configurations now work on MPS. On macOS 26+, install the `kernels` package for the best performance, which enables the optimized Metal kernels; otherwise a naive fallback is used. The MPS path requires torch >= 2.9.

The last remaining feature for support parity is the 8bit optimizers, which will land in a future release.

### CPU performance on x86-64 and ARM64
Blockwise quantization and dequantization on CPU are considerably faster, mostly from better SIMD usage plus some compile flag tuning. Improvements range from 1.1x to over 20x depending on op, dtype, and hardware, with the largest gains on fp16 and on x86-64 CPUs without AVX-512. The LLM.int8() matmul on CPU was improved as well. See #1968 for benchmarks.

### Reduced host-side CPU overhead
Reduced Python dispatch overhead, especially on the CUDA/ROCm backend (#1953).

### Windows on ARM CPU support
Windows ARM64 CPU wheels are now built with NEON-optimized kernels (#1959), with nightly test coverage added (#1962).

### New optimizer support
* CPU optimizers are now supported for both 32-bit and 8-bit blockwise (#1901).
* Intel XPU gained paged optimizer support (#1898) and support for the LARS and LAMB optimizers (#1902).
* Fixed Lion to use decoupled weight decay (#1993, #2001).
* Other optimizer fixes (#1869, #1998, #1855).

### NVIDIA CUDA
* Added CUDA 13.2 build wheels and nightly test coverage (#1925).
* Smaller wheels: reduced the CUDA build matrix and added a closest-version fallback for library loading (#1980).

### Intel XPU
* Added a oneAPI 2026 build; wheels now package both the 2025 and 2026 variants and pick the right one at runtime based on the PyTorch XPU version (#2002).
* Fixed `gemv_4bit` bf16 correctness on Intel Arc A-series (Alchemist) GPUs (#1942).

## 🚨 Breaking Changes
* Minimum PyTorch version is now 2.4 (#1926).
* Removed deprecated APIs: the `research` module, non-blockwise (`block_wise=False`) optimizers, and legacy dynamic quantization functions, along with their CUDA/HIP kernels (#1871, #1880).
* Removed legacy sparse functionality (`spmm_coo`, `spmm_coo_very_sparse`) and dropped the cusparse/hipsparse dependencies (#1881).

## Deprecations
* `igemm`, `batched_igemm`, and `check_matmul` are deprecated and now emit warnings (#2003).
* Passing 4-bit weights quantized in transposed `[in_features, out_features]` orientation to `matmul_4bit` now emits a `DeprecationWarning`. Support is likely to be removed in the future. This is not a typical use case (#1949).

## Other improvements and bug fixes
This release also includes a number of other improvements, bug fixes, and documentation updates. See the full changelog below.


## What's Changed
* [CI] Test against PyTorch 2.10 by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1876
* Simplest MPS backend: adding kernels using kernel builder and kernels-community by @MekkCyber in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1875
* Fix ruff lint and format issues in agents/ scripts by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1879
* CI: add NVIDIA A10 runner for tests by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1874
* [Docs] Create quickstart guide by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1872
* Add BNB_ROCM_VERSION and ROCM_VERSION for ROCm/PyTorch version mismatch by @lucbruni-amd in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1878
* Adding support for building for AMD on Windows by @rwfsmith in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1846
* doc: fix a typo by @Freed-Wu in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1850
* Fix QuantState and dict conversions by @cyyever in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1729
* Fix Params4bit attribute access for FSDP state_dict traversal by @TimDettmers in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1866
* Add LARS to str2optimizer32bit dictionary by @Mr-Neutr0n in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1855
* Remove deprecated APIs: research module, non-blockwise optimizers, and legacy quantization functions by @TimDettmers in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1871
* Remove non-blockwise 8-bit optimizer and legacy quantization CUDA/HIP kernels by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1880
* Remove legacy sparse functionality by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1881
* Unify CUDA and HIP kernel sources via compat.cuh portability layer by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1877
* Fix GlobalOptimManager.override_config not propagating to optimizer by @TimDettmers in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1869
* Replace print/warnings with logging in library modules by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1883
* fix: Replace hard-coded precision thresholds with std-based bounds by @TimDettmers in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1864
* Fix 4-bit quantization for weight matrices not divisible by blocksize by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1884
* [ROCm] Replace compile-time warp size with runtime query in host code by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1885
* [ROCm] Enable more targets by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1886
* Create SECURITY.md by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1892
* cuda_specs.py: fix version tag string for ROCm/CUDA library lookup by @eliasmagn in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1889
* [ROCm] Enable blocksize 32 4-bit quantization and GEMV kernels on AMD CDNA by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1887
* Honor out in matmul_4bit by @ailuntz in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1893
* Enable Paged Optimizer Support for XPU by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1898
* fix: accept **kwargs in Params4bit and Int8Params constructors by @ajmeese7 in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1900
* Fix LARS/LAMB optimizer support and non-contiguous tensor handling on XPU by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1902
* Enable CPU Optimizer Support for bitsandbytes by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1901
* Update CUDA/ROCm setup tests by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1899
* update legend by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1909
* Guard SCB access in Linear8bitLt by @ailuntz in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1897
* [ROCm] Bump ROCm version to 7.2.1 by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1914
* Fix XPU dequantize ops for non-contiguous tensors by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1911
* use importlib machinery to check for habana plugin by @scw in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1910
* [ROCm] Windows workflow for creating wheels with ROCm 7.2.1 support by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1915
* Slightly relax `maxerr1` threshold for fp32 in `test_gemv_4bit` by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1919
* Fix torch.compile graph breaks from Params4bit __getattr__ (#1904, #1917) by @Titus-von-Koeller in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1916
* remove deprecated tests by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1922
* Bump ROCm 7.1 and 7.2 to the latest point release by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1924
* ci: add CUDA 13.2 build and nightly test support by @Titus-von-Koeller in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1925
* Enable XPU for blockwise quantization and FSDP tests by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1921
* [ROCm] Try multiple hipBLASLt heuristic algos and fall back to fp32 for unsupported int8 shapes by @Abdennacer-Badaoui in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1934
* Bump Linux ROCm build to 7.2.3 (#1) by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1938
* fix: replace all instances of deprecated torch._check_is_size with torch._check by @neil-the-nowledgeable in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1940
* docs(install): note aarch64 wheels are aarch64-sbsa, not L4T (Jetson) by @neil-the-nowledgeable in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1941
* Fix `gemv_4bit` bfloat16 correctness on Intel Arc A-series (Alchemist) GPUs by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1942
* CI Updates by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1947
* chore: bump minimum PyTorch version from 2.3 to 2.4 by @Titus-von-Koeller in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1926
* CI: Update to test with torch 2.12.0 and nightly by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1948
* [CUDA] New 4bit GEMM kernels for inference by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1949
* 4bit GEMM fix: per-device cudaFuncSetAttribute cache by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1952
* Fix gemv test on avx512bf16 cpu by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1956
* Reduce Python CPU overhead and improve validation messages by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1953
* Fix target specific option mismatch during OpenMP loop inlining under GCC 16 by @Soddentrough in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1954
* Add Windows ARM64 wheel build support with NEON optimization by @pdeep854 in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1959
* Test workflow for WoA by @pdeep854 in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1961
* CI: Add Windows CPU ARM64 to nightly tests by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1962
* perf: improve default/fallback backend implementation for blockwise quantization ops by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1960
* Update README support table by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1967
* perf: Improve CPU performance on x64 and arm64 by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1968
* fix: ensure absmax_offset is of type float32 before passing to gemm_4bit by @kathsucurry in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1971
* Specify kernel `version` when loading CPU `gemm_4bit_forward` from the Hub by @jiqing-feng in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1972
* CI: compat for windows-2025 + vs2026 by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1975
* CI: misc cleanup/improvement by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1976
* CI: pin GitHub Actions to SHA by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1977
* Reduce CUDA build matrix, better fallback for lib loading by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1980
* chore(deps): bump the actions group with 2 updates by @dependabot[bot] in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1982
* MPS: improved backend by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1983
* Make doc builds faster by @mishig25 in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1986
* chore(deps): bump actions/setup-python from 6.2.0 to 6.3.0 in the actions group by @dependabot[bot] in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1987
* [ROCm] Fused 4-bit SIMT GEMM by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1979
* Fix compat with scikit-build-core 1.0.0 by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1989
* Fix Lion to use decoupled weight decay (default + CUDA 32-bit) by @eaglstun in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1993
* Enable non-contiguous quantize_4bit tests for the MPS backend by @egeozkoc in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1994
* Handle non-contiguous inputs in CPU blockwise quantize/dequantize by @egeozkoc in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1996
* ci: bump Linux ROCm support to 7.2.4 by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1997
* Deprecate igemm, batched_igemm, check_matmul APIs by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2003
* build: cleanup unused metal build code by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2004
* XPU: Add oneAPI 2026 build; package both 2025 and 2026 variants by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2002
* Fix Lion to use decoupled weight decay in the Triton 32-bit kernel by @eaglstun in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2001
* ci: add ROCm 7.14 support and support more architectures, drop ROCm 6.2 and 6.3  by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2007
* fix(parametrize): cache-gate hooks leak the global parametrize cache under activation checkpointing (all dequantized params retained) by @pjordanandrsn in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1999
* CI: Test with torch 2.13 by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2008
* cleanup: remove unused CUDA install scripts by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2009
* fix(optim): honor user-provided max_unorm in LAMB (+ 8-bit arg guards) by @egeozkoc in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1998
* fix(rocm): avoid SIMT workgroup-count resonance by @sstamenk in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2012
* chore(deps): bump softprops/action-gh-release from 3.0.1 to 3.0.2 in the actions group by @dependabot[bot] in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2013
* docs: update AMD section by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2015
* (docs) update XPU section by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2016
* Update README by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2017
* Update supported platforms in installation guide by @matthewdouglas in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/2019

## New Contributors
* @MekkCyber made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1875
* @lucbruni-amd made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1878
* @rwfsmith made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1846
* @Freed-Wu made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1850
* @Mr-Neutr0n made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1855
* @eliasmagn made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1889
* @ailuntz made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1893
* @ajmeese7 made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1900
* @scw made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1910
* @neil-the-nowledgeable made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1940
* @Soddentrough made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1954
* @pdeep854 made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1959
* @kathsucurry made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1971
* @mishig25 made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1986
* @eaglstun made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1993
* @egeozkoc made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1994
* @pjordanandrsn made their first contribution in https://github.com/bitsandbytes-foundation/bitsandbytes/pull/1999

**Full Changelog**: https://github.com/bitsandbytes-foundation/bitsandbytes/compare/0.49.2...0.50.0