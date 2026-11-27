#!/bin/sh
# run from the repository root
python3 guopsaem_root/verifier_v4/verify_v4.py --dictionary guopsaem_root/verifier_v4/attacks/cases/gz_plain/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/gz_plain/p.json --proof guopsaem_root/verifier_v4/attacks/cases/gz_plain/proof.jsonl.gz
guopsaem_root/verifier_v4/build/verify_v4 --dictionary guopsaem_root/verifier_v4/attacks/cases/gz_plain/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/gz_plain/p.json --proof guopsaem_root/verifier_v4/attacks/cases/gz_plain/proof.jsonl.gz
python3 guopsaem_root/verifier_v4/verify_v4.py --dictionary guopsaem_root/verifier_v4/attacks/cases/gz_plain/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/gz_plain/p.json --proof guopsaem_root/verifier_v4/attacks/cases/gz_plain/proof.jsonl.gz --digest-only
guopsaem_root/verifier_v4/build/verify_v4 --dictionary guopsaem_root/verifier_v4/attacks/cases/gz_plain/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/gz_plain/p.json --proof guopsaem_root/verifier_v4/attacks/cases/gz_plain/proof.jsonl.gz --digest-only
