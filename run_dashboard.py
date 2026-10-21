"""
Start the CodeTune dashboard (Milestone 5):

    python run_dashboard.py                 # http://127.0.0.1:8765
    python run_dashboard.py --port 9000 --no-browser
    python run_dashboard.py --ml            # also show the ML selector (trains once if needed)

Stop with Ctrl+C. The server only listens on this computer (127.0.0.1).
"""

import argparse
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codetune.dashboard import make_server


def main():
    ap = argparse.ArgumentParser(description="CodeTune dashboard")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--ml", action="store_true", help="enable the ML selector panel")
    args = ap.parse_args()

    ml = None
    if args.ml:
        from codetune.ml import MLPassSelector
        print("Loading ML selector (trains once if no saved model)...")
        ml = MLPassSelector.load_or_train()
        if ml.eval_report:
            print(ml.eval_report.to_text())

    from codetune.copilot.llm import GeminiClient, load_dotenv
    env_file = load_dotenv()
    server = make_server("127.0.0.1", args.port, ml)
    gem = GeminiClient()
    if env_file:
        print(f"Loaded settings from {env_file}")
    print("Gemini: " + (f"API key found in the environment (model {gem.model})" if gem.available else
                        "off (add GEMINI_API_KEY=your_key to the .env file and restart)"))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"\nCodeTune dashboard running at {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()