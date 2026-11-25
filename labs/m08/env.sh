# Source in the shell used for lessons 30–32; no global Solana config or wallet changes.
m08_cache=${XDG_CACHE_HOME:-$HOME/.cache}/web3-study/m08
export PATH="$m08_cache/venv/bin:$m08_cache/solana-release/bin:$PATH"
unset m08_cache
