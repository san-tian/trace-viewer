#!/bin/bash
# 重新编译演示站点到 docs/（GitHub Pages 发布根）
cd "$(dirname "$0")/.."
python3 viewer/build_viewer.py --raw demo/data/raw --judged demo/data/judged \
  --out docs --config demo/config.json --scores-csv
