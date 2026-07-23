"""
Claude Code CLI (`claude -p`) をサブプロセスとして呼び出す共通ヘルパー。

Anthropic API を直接叩かないため従量課金は発生せず、
Claude Pro/Max プラン(ローカル)または CLAUDE_CODE_OAUTH_TOKEN(CI)の枠内で動作します。

judge_with_claude.py / build_profile.py から共用します。
"""

import json
import os
import shutil
import subprocess
import sys

DEFAULT_MODEL = os.environ.get("DIGEST_CLAUDE_MODEL", "sonnet")


def find_claude() -> str:
    """claude 実行ファイルのパスを解決する。見つからなければ終了する。"""
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    found = shutil.which("claude")
    if found:
        return found
    for cand in [
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]:
        if os.path.exists(cand):
            return cand
    sys.exit(
        "claude CLI が見つかりません。https://claude.ai/install.sh でインストールし、"
        "`claude` でログインしてください(環境変数 CLAUDE_BIN でパス指定も可)"
    )


def has_claude() -> bool:
    """claude CLI が使えるかどうかを、終了せずに判定する。"""
    if os.environ.get("CLAUDE_BIN"):
        return os.path.exists(os.environ["CLAUDE_BIN"])
    if shutil.which("claude"):
        return True
    return any(
        os.path.exists(p)
        for p in (
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.claude/local/claude"),
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
        )
    )


def run_claude_text(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 1800,
    claude_bin: str = None,
) -> str:
    """claude -p にプロンプトを引数として渡し、応答テキストを返す。

    プロンプトはコマンドライン引数として渡すため、呼び出し側で長さを
    抑える責任がある(目安: 数百KB以内。ARG_MAX に依存)。
    """
    cmd = [claude_bin or find_claude(), "-p", "--model", model, "--output-format", "json", prompt]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"claude実行失敗 (exit {res.returncode}): {res.stderr[:500]}")
    outer = json.loads(res.stdout)
    if outer.get("is_error"):
        raise RuntimeError(f"claude応答がエラーです: {str(outer)[:300]}")
    return outer.get("result", "")
