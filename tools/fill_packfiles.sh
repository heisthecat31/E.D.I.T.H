#!/bin/bash
# Build + smoke-test her lobby until the game stops asking for texture packfiles it cannot find:
# each round takes the "Cannot find resource 0xAE49FAD43254367A:<name>" names from the log,
# fetches those names and their neighbours (+-16..64, packfile names count up per mip) from the
# 2018 data (RawTexturePackfileWin7 51e6cb2d64c65e4f) into out/her_assets/ae49fad43254367a.
E=/j/EchoVR-Tools-Launcher/EchoEnhancements
EV=/j/EchoVR-Tools-Launcher/EchoCombat/evrtool/evrtool.exe
D18="$(cygpath -w "/j/echo-summer-dist/Echo VR Christmas 2018/_data/5868485946/rad15/win7")"
cd $E
for round in 1 2 3 4 5 6; do
  python -I tools/build_satellite.py --her-model --with-port --at 0 2.3 0 --launch --seconds 150 > out/fill_round.log 2>&1
  f=$(ls -t /h/ready-at-dawn-echo-arena/_local/r14logs/*.log | head -1)
  grep -oE "0xAE49FAD43254367A:0x[0-9A-F]{16}" "$f" | cut -d: -f2 | sed 's/0x//' | tr 'A-F' 'a-f' | sort -u > out/pf_round.txt
  n=$(wc -l < out/pf_round.txt)
  echo "round $round: $n missing packfile names; $(grep -E 'loaded|fail ' out/fill_round.log | tr '\n' ' ' | cut -c1-160)"
  [ "$n" = 0 ] && break
  python -I - <<'EOF'
seeds = {int(l, 16) for l in open(r"out\pf_round.txt").read().split()}
c = sorted({(b + k) & 0xFFFFFFFFFFFFFFFF for b in seeds for k in range(-16, 64)})
open(r"out\pf_cands_round.txt", "w").write(" ".join(f"{v:016x}" for v in c))
EOF
  $EV find "$D18" $(cat out/pf_cands_round.txt) | grep "^51e6cb2d64c65e4f" | cut -d' ' -f1 > out/pf_get_round.txt
  rm -rf out/pf_src_round
  $EV get "$D18" "$(cygpath -w out/pf_get_round.txt)" "$(cygpath -w out/pf_src_round)" > /dev/null
  cp out/pf_src_round/51e6cb2d64c65e4f/* out/her_assets/ae49fad43254367a/ 2>/dev/null
  echo "   now $(ls out/her_assets/ae49fad43254367a | wc -l) packfiles"
done
