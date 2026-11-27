# 보호막 12에서 ~법 제시 — 제시한 쪽 패 (검증 통과)

받은 쪽(보호막 11에서 법을 받음)이 법률불소급의원칙(→칙)으로 이김. 4코어로 나눠 계산(`shield_split.py`)하다가
이기는 수가 나와 멈춤. 근거 자리 1,414,180개(끝난 다른 수 2가지의 근거 자리도 함께 들어 있음).
파일이 커서 40MB 조각으로 나눠 두었습니다. 다시 확인하려면:

```
cd eoinjeong_root/shield/examples/beop/present_법_12
cat present_법_12.json.gz.part* > present_법_12.json.gz
cat route.tgz.part* | tar xzf -
mv cert_beop12s.json.route present_법_12.json.route
python3 ../../../shield_verify.py present_법_12.json.gz
```
