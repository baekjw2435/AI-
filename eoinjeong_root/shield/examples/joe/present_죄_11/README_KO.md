# 보호막 11에서 ~죄 제시 — 제시한 쪽 승 (검증 통과)

받은 쪽(보호막 10에서 죄를 받음)이 낼 수 있는 96가지가 모두 짐. 근거 자리 2,462,031개, 쓴 루트 단어가 있는 루트 자리의
solver_v5 증명서 3,842개(verify_v4 수락). 4코어로 나눠 계산(`shield_split.py`, 묶음마다 한도 6시간, 약 1시간 20분).

파일이 커서 40MB 조각으로 나눠 두었습니다. 다시 확인하려면:

```
cd eoinjeong_root/shield/examples/joe/present_죄_11
cat present_죄_11.json.gz.part* > present_죄_11.json.gz      # sha256 = MANIFEST.json의 certificate_json_gz_sha256
cat route.tgz.part* | tar xzf -                               # cert_s11.json.route/ 가 생김
mv cert_s11.json.route present_죄_11.json.route
python3 ../../../shield_verify.py present_죄_11.json.gz       # 1시간쯤, 메모리 4GB
```
