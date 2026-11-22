#!/usr/bin/env bash
# Only downloads build tools; no wallet, node or shell profile is touched.
set -euo pipefail
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)
    platform=darwin-arm64
    hashes=('PwvdcKxniBoIic163Gw8t7rIOfE8ZfV2mCM2WOXnGdsUbCJRvkqCWq4qidkUORbibhfiRTyw3991hMFL8/qEfw==' 'lO2aEhJfTOksC4V2Qhz6kH4RztPKd/rMsv6GJLfIWKMQ9Q/1TmMzpyGELCSUp28YwYqhC7gTlFYMkxDTuvyqiw==' 'JNeu3+A3f/npXLn8SR8EahVcqE7BpO9VQZMcPvSIy27/RNc1GsoEBvSLR99aSvt8sGKWAgNg/EzrtjAPq6mxcA==') ;;
  Darwin-x86_64)
    platform=darwin-amd64
    hashes=('0P18bZyXiCJ5YJMQ+FgOE3WToqt7qBp8eyeBWFAIHX79hwN8RWtvdBWJ6ZcYH14lWZVuN8oYi8Wkth/t3jAa8g==' 'K1ZV5SLcq9B6cMmtZYRB0YyIbhrhLgdMyKzjMzQmIohxkC7+gtrOUwzMMFTU5IedGgaUXBCFH5Bp5DGUkJ9qpw==' 'OgwzwY+FsGrsPyDv4mmbhOwARO8s37YHrm2qaNzgSH4VlKnXgJCrnoT7bpgOhLyBPtxXjBT8L2E3b79deesXRg==') ;;
  Linux-x86_64)
    platform=linux-amd64
    hashes=('/HQddyTanVOJKgvilmZrf8VOf7mhvwrWb59W73w5W5flX7b6zNh9CR6hKZzJwiRRi5Sxk/JOFEYIeKsQx7Teqg==' 'XUpTM2rwtkF8BJ02dae38NNZAx5QfycWRpdR2RmSgOJnasvXuvN58whDVLjQu8IDHEV/fCNIa49aE8V74pmDwQ==' '+XmShybEaxfCrr0OUUZwYEy2OnYZt5pHH9TzBtLv3+VrK0O/ANuNSVEahqNhKHlgX7GRJ59383ofNhxkRWIYTg==') ;;
  *) echo '本安装器支持 macOS arm64/x86_64 和 Linux x86_64；其他平台须自行准备同版工具。' >&2; exit 1 ;;
esac
case "$platform" in
  darwin-*) compiler=macosx-amd64; sha=81515b0e53deaa266d549545ccaac0a5a96e6d4e8201c77f673b2c710976d9ea ;;
  linux-*) compiler=linux-amd64; sha=9a0fb7e0db2c0641dbae1c5cc645dc686820c83af516226abb1c0a2f76636f25 ;;
esac
cache="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04"
mkdir -p "$cache/bin"
work=$(mktemp -d "$cache/download.XXXXXX")
trap 'rm -rf "$work"' EXIT
bins=(forge cast anvil)
for i in 0 1 2; do
  bin=${bins[$i]}; pkg=$bin-$platform
  printf '下载并核验 %s 1.7.1…\n' "$pkg"
  curl -fLsS "https://registry.npmjs.org/@foundry-rs/$pkg/-/$pkg-1.7.1.tgz" -o "$work/$bin.tgz"
  [[ $(openssl dgst -sha512 -binary "$work/$bin.tgz" | openssl base64 -A) == "${hashes[$i]}" ]] || { echo "摘要不符: $pkg" >&2; exit 1; }
  tar -xzf "$work/$bin.tgz" -C "$work" "package/bin/$bin"
done
printf '下载并核验 solc 0.8.28 (%s)…\n' "$compiler"
curl -fLsS "https://raw.githubusercontent.com/ethereum/solc-bin/gh-pages/$compiler/solc-$compiler-v0.8.28+commit.7893614a" -o "$work/package/bin/solc"
[[ $(openssl dgst -sha256 < "$work/package/bin/solc" | awk '{print $NF}') == "$sha" ]] || { echo '摘要不符: solc' >&2; exit 1; }
chmod +x "$work/package/bin/solc"
for bin in forge cast anvil solc; do "$work/package/bin/$bin" --version; done
mv "$work/package/bin/"{forge,cast,anvil,solc} "$cache/bin/"
printf '工具已就绪。在本终端执行：\nexport PATH="%s/bin:$PATH"\nexport FOUNDRY_SOLC="%s/bin/solc"\n' "$cache" "$cache"
