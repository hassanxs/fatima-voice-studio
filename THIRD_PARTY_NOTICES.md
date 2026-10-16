# Third-party notices

Fatima Voice Studio's own code is MIT licensed (see `LICENSE`). It ships with, or downloads on request,
the following third-party software and models, each under its own licence.

## Shipped in the installer

| Component | Licence | Source |
|---|---|---|
| Python 3.13 (embeddable distribution) | PSF License 2.0 | https://www.python.org |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| python-soundfile | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| libsndfile (bundled in python-soundfile) | LGPL-2.1 | https://github.com/libsndfile/libsndfile |
| lameenc, with the LAME MP3 encoder | LGPL-3.0 (LAME: LGPL-2.0) | https://github.com/chrisstaite/lameenc |
| num2words | LGPL-2.1 | https://github.com/savoirfairelinux/num2words |
| sherpa-onnx, sherpa-onnx-core (with ONNX Runtime) | Apache-2.0 (ONNX Runtime: MIT) | https://github.com/k2-fsa/sherpa-onnx |
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | https://github.com/encode/starlette |
| Uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn |
| Pydantic, pydantic-core, pydantic-settings | MIT | https://github.com/pydantic |
| HTTPX, HTTPCore | BSD-3-Clause | https://github.com/encode/httpx |
| AnyIO | MIT | https://github.com/agronholm/anyio |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| MCP Python SDK | MIT | https://github.com/modelcontextprotocol/python-sdk |
| pywin32 | PSF | https://github.com/mhammond/pywin32 |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |
| sse-starlette | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| jsonschema, jsonschema-specifications, referencing, rpds-py | MIT | https://github.com/python-jsonschema |
| cryptography | Apache-2.0 or BSD-3-Clause | https://github.com/pyca/cryptography |
| Microsoft Visual C++ runtime (msvcp140, vcruntime140, vcomp140 and related DLLs, in `runtime/`) | Microsoft Visual C++ redistributable terms | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| cffi | MIT | https://github.com/python-cffi/cffi |
| pycparser | BSD-3-Clause | https://github.com/eliben/pycparser |
| OpenTelemetry API | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python |
| attrs | MIT | https://github.com/python-attrs/attrs |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | BSD-3-Clause | https://github.com/pallets/click |
| h11 | MIT | https://github.com/python-hyper/h11 |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| PyJWT | MIT | https://github.com/jpadilla/pyjwt |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| six | MIT | https://github.com/benjaminp/six |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection, annotated-types, annotated-doc | MIT | https://github.com/pydantic |
| httpx-sse | MIT | https://github.com/florimondmanca/httpx-sse |
| Geist, Geist Mono fonts | SIL Open Font License 1.1 | https://github.com/vercel/geist-font |

Exact versions are in `packaging/requirements-lock.txt`; each package's licence text is in its
`*.dist-info` folder inside the installed `python\Lib\site-packages`.

pystray, num2words, lameenc (with LAME) and libsndfile are LGPL. They are shipped unmodified as separate files (Python
source and DLLs/extension modules), which you may replace with your own builds.

## Downloaded by the app when you choose to

These are not part of the installer. The app downloads them from their publishers when you click Download,
and checks each file against its published SHA-256.

| Component | Licence | Source |
|---|---|---|
| llama.cpp engine (`llama-tts`), incl. ggml | MIT | https://github.com/ggml-org/llama.cpp |
| NVIDIA CUDA runtime (in the CUDA engine downloads) | NVIDIA CUDA EULA | redistributed by llama.cpp |
| whisper.cpp (`whisper-cli`), incl. ggml | MIT | https://github.com/ggml-org/whisper.cpp |
| whisper.cpp graphics card builds (CUDA 13.4, CUDA 12.4, Vulkan), built by this project from the same source | MIT | https://github.com/hassanxs/fatima-voice-studio/releases/tag/whisper-b5454 (they use the CUDA files of the engine download) |
| Qwen3-TTS 12Hz 1.7B Base (GGUF, Q8 and Q4) | Apache 2.0 | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base, GGUF by ggml-org |
| Fish Audio S2 Pro (GGUF, Q8 and Q6), optional second voice model | Fish Audio Research License (non-commercial; commercial use needs a licence from Fish Audio). Built with Fish Audio. | https://huggingface.co/fishaudio/s2-pro, GGUF by rodrigomt (https://huggingface.co/rodrigomt/s2-pro-gguf) |
| s2.cpp (S2 Pro engine, `s2.exe`), built by this project with pull requests #50-#52 and a seed option | Fish Audio Research License, incl. ggml (MIT) | https://github.com/rodrigomatta/s2.cpp; builds: https://github.com/hassanxs/fatima-voice-studio/releases/tag/s2cpp-2c33261 (LICENSE.md and NOTICE.txt inside; they use the CUDA files of the engine download) |
| OmniVoice (GGUF, Q8 and Q4), optional third voice model, with the Higgs Audio v2 audio tokenizer (Boson AI) | CC-BY-NC 4.0 (non-commercial; the code is Apache 2.0); the tokenizer is under Boson AI's own licence | https://huggingface.co/k2-fsa/OmniVoice, GGUF by Serveurperso (https://huggingface.co/Serveurperso/OmniVoice-GGUF) |
| omnivoice.cpp (OmniVoice engine, `tts-server.exe`), built by this project with a steps option | MIT, incl. ggml (MIT) | https://github.com/ServeurpersoCom/omnivoice.cpp; builds: https://github.com/hassanxs/fatima-voice-studio/releases/tag/omnivoice-1a468d8 (LICENSE.txt and NOTICE.txt inside; the CUDA build uses the CUDA files of the engine download) |
| Whisper base, small, medium, large-v3 turbo, large-v3 (ggml) | MIT | https://huggingface.co/openai, ggml by ggerganov |
| UVR MDX-Net Voc_FT voice separator (ONNX) | MIT (Ultimate Vocal Remover) | https://github.com/Anjok07/ultimatevocalremovergui, ONNX by k2-fsa/sherpa-onnx |
| ffmpeg 9.0.2 "essentials" build (only if ffmpeg isn't already on the PC) | GPL-3.0, a separate program the app runs | https://github.com/GyanD/codexffmpeg (builds of https://ffmpeg.org) |

## Audio you make

The voice models above allow commercial use of their output. Cloning a voice still needs the permission of the
person it belongs to: only add voices that are yours or that you have the right to use.
