// Regression for the static_labels tag counter (found by the Astra review, 2026-11-05):
// a cumulative int counter overflowed after about 4.66 million normalizations on this model.
// Now tags are per call (s + 1) and `mark` is reset on every call. This test perturbs `mark`
// with extreme values between calls and checks that labels never change; build it with
// -fsanitize=undefined so any signed overflow would be reported.
//   g++ -O1 -g -fsanitize=undefined -std=c++17 -o stamp_regression stamp_regression.cpp -lz
//   ./stamp_regression ../../words_3436.txt 3436
#define main verifier_program_main
#include "../verify_v4.cpp"
#undef main
#include <climits>
#include <fstream>
#include <sstream>
int main(int argc, char** argv) {
  std::ifstream f(argv[1]);
  std::stringstream ss; ss << f.rdbuf();
  Model m(ss.str(), atoi(argv[2]));
  m.static_labels(m.full.data());
  const std::vector<int> want = m.labels;
  const int fills[] = {INT_MAX, INT_MIN, -1, 0, 1, 2, 461, 462};
  for (int i = 0; i < 2000; i++) {
    std::fill(m.mark.begin(), m.mark.end(), fills[i % 8]);
    m.static_labels(m.full.data());
    if (m.labels != want) { fprintf(stderr, "labels changed at call %d\n", i); return 2; }
  }
  printf("ok: 2000 calls, labels stable\n");
  return 0;
}
