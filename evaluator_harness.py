import json
import sys
import traceback

def run_simulation(priority_fn, sequences, bin_size=100.0):
    total_bins = 0
    total_vol = 0.0

    for seq in sequences:
        bins = []
        total_vol += sum(seq)

        for item in seq:
            best_idx = -1
            max_score = -float("inf")

            for idx, cap in enumerate(bins):
                if cap >= item:
                    try:
                        score = float(priority_fn(item, cap))
                    except Exception:
                        score = -1e9
                    if score > max_score:
                        max_score = score
                        best_idx = idx

            if best_idx != -1:
                bins[best_idx] -= item
            else:
                bins.append(bin_size - item)

        total_bins += len(bins)

    if total_bins == 0:
        return 0.0
    return max(0.0, min(1.0, total_vol / (total_bins * bin_size)))

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input:
            print(json.dumps({"success": False, "error": "Empty input"}))
            return

        payload = json.loads(raw_input)
        code = payload.get("code", "")
        sequences = payload.get("sequences", [])

        local_vars = {}
        exec(code, {}, local_vars)
        priority_fn = local_vars.get("priority")
        if not priority_fn:
            print(json.dumps({"success": False, "error": "Missing priority function"}))
            return

        fitness = run_simulation(priority_fn, sequences)
        print(json.dumps({"success": True, "fitness": fitness}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e), "trace": traceback.format_exc()}))

if __name__ == "__main__":
    main()
