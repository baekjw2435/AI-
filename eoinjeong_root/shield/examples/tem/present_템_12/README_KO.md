# 보호막 12에서 ~템 제시 — 제시한 쪽 승 (검증 통과)

받은 쪽(보호막 11에서 템을 받음)이 낼 수 있는 25가지가 모두 짐. 근거 자리 1,641,540개.
4코어로 나눠 계산(`shield_split.py`). 파일이 커서 40MB 조각으로 나눠 두었습니다. 다시 확인하려면:

```
cd eoinjeong_root/shield/examples/tem/present_템_12
cat present_템_12.json.gz.part* > present_템_12.json.gz      # sha256 = MANIFEST.json의 certificate_json_gz_sha256
cat route.tgz.part* | tar xzf -                              # cert_tem12s.json.route/ 가 생김
mv cert_tem12s.json.route present_템_12.json.route
python3 ../../../shield_verify.py present_템_12.json.gz
```
