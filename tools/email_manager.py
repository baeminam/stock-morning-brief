"""
REPORT_EMAIL secret manager (PC app).

GitHub Secrets cannot be read back or edited by hand without opening the
website, so this small GUI keeps the master recipient list locally and
overwrites the REPORT_EMAIL Actions secret via the GitHub API.

Requirements:
    pip install requests pynacl
    (tkinter ships with Python)

You need a GitHub Personal Access Token with access to the repo:
    GitHub → Settings → Developer settings → Personal access tokens
    → Tokens (classic) → Generate new token → scope: public_repo (or repo)

Run:
    python tools/email_manager.py        (console)
    pythonw tools/email_manager.py       (no console, see 이메일관리자.bat)
"""

import base64
import json
import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import requests
from nacl import encoding, public

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".stock_brief_email_manager.json"
DEFAULT_REPO = "baeminam/stock-morning-brief"
SECRET_NAME = "REPORT_EMAIL"
TOKEN_GUIDE_URL = "https://github.com/settings/tokens"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"repo": DEFAULT_REPO, "token": "", "recipients": []}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def update_report_email_secret(token: str, repo: str, recipients: list[str]) -> None:
    """Overwrite the REPORT_EMAIL Actions secret with the comma-joined list."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    value = ", ".join(recipients)

    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
        timeout=15,
    )
    if r.status_code == 404:
        raise RuntimeError("레포를 찾을 수 없거나 토큰 권한이 부족합니다 (404)")
    if r.status_code in (401, 403):
        raise RuntimeError("토큰 인증 실패 — PAT와 public_repo 권한을 확인하세요")
    r.raise_for_status()
    pk = r.json()

    sealed = public.SealedBox(
        public.PublicKey(pk["key"].encode("utf-8"), encoding.Base64Encoder)
    ).encrypt(value.encode("utf-8"))

    r2 = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{SECRET_NAME}",
        headers=headers,
        json={"encrypted_value": base64.b64encode(sealed).decode("utf-8"), "key_id": pk["key_id"]},
        timeout=15,
    )
    if r2.status_code not in (201, 204):
        raise RuntimeError(f"시크릿 등록 실패: {r2.status_code} {r2.text[:200]}")


class EmailManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("일일 종목 분석 리포트 - 수신자 관리")
        self.geometry("520x480")
        self.resizable(False, False)

        cfg = load_config()
        self._build_widgets(cfg)
        self._refresh_list()

    def _build_widgets(self, cfg: dict):
        pad = {"padx": 12, "pady": 4}

        info = (
            "GitHub Actions의 REPORT_EMAIL 시크릿을 이 PC에서 직접 수정합니다.\n"
            "시크릿 값은 조회할 수 없으므로, 이 앱의 목록이 전체 수신자 목록이 됩니다."
        )
        tk.Label(self, text=info, justify="left", fg="#555").pack(anchor="w", **pad)

        # Token
        token_frame = tk.LabelFrame(self, text="GitHub 토큰 (PAT, public_repo 권한)")
        token_frame.pack(fill="x", **pad)
        self.token_var = tk.StringVar(value=cfg.get("token", ""))
        tk.Entry(token_frame, textvariable=self.token_var, show="*", width=46).pack(
            side="left", padx=8, pady=8
        )
        tk.Button(
            token_frame, text="토큰 발급 페이지", command=self._open_token_page
        ).pack(side="left", padx=4)

        # Repo
        repo_frame = tk.Frame(self)
        repo_frame.pack(fill="x", **pad)
        tk.Label(repo_frame, text="레포:").pack(side="left")
        self.repo_var = tk.StringVar(value=cfg.get("repo", DEFAULT_REPO))
        tk.Entry(repo_frame, textvariable=self.repo_var, width=40).pack(side="left", padx=6)

        # Recipients
        list_frame = tk.LabelFrame(self, text="수신 이메일 목록")
        list_frame.pack(fill="both", expand=True, **pad)
        self.listbox = tk.Listbox(list_frame, height=10, activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._recipients = list(cfg.get("recipients", []))

        edit_frame = tk.Frame(list_frame)
        edit_frame.pack(fill="x", padx=8, pady=8)
        self.email_var = tk.StringVar()
        entry = tk.Entry(edit_frame, textvariable=self.email_var, width=32)
        entry.pack(side="left")
        entry.bind("<Return>", lambda e: self._add_email())
        tk.Button(edit_frame, text="추가", command=self._add_email).pack(side="left", padx=4)
        tk.Button(edit_frame, text="선택 삭제", command=self._remove_email).pack(side="left", padx=4)

        # Apply
        apply_frame = tk.Frame(self)
        apply_frame.pack(fill="x", **pad)
        tk.Button(
            apply_frame,
            text="GitHub에 적용 (REPORT_EMAIL 덮어쓰기)",
            command=self._apply,
            bg="#1a73e8",
            fg="white",
            font=("Malgun Gothic", 10, "bold"),
            height=2,
        ).pack(fill="x")

        self.status_var = tk.StringVar(value="준비됨")
        tk.Label(self, textvariable=self.status_var, fg="#1a73e8", wraplength=490, justify="left").pack(
            anchor="w", **pad
        )

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for e in self._recipients:
            self.listbox.insert(tk.END, e)

    def _add_email(self):
        email = self.email_var.get().strip()
        if not email:
            return
        if "@" not in email or "." not in email:
            messagebox.showwarning("형식 오류", "올바른 이메일 주소를 입력하세요.")
            return
        if email in self._recipients:
            self.status_var.set(f"이미 등록된 주소입니다: {email}")
            return
        self._recipients.append(email)
        self.email_var.set("")
        self._refresh_list()
        self._save_local()
        self.status_var.set(f"추가됨: {email} (아직 GitHub에는 미적용)")

    def _remove_email(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        removed = self._recipients.pop(sel[0])
        self._refresh_list()
        self._save_local()
        self.status_var.set(f"삭제됨: {removed} (아직 GitHub에는 미적용)")

    def _save_local(self):
        save_config(
            {
                "repo": self.repo_var.get().strip(),
                "token": self.token_var.get().strip(),
                "recipients": self._recipients,
            }
        )

    def _open_token_page(self):
        import webbrowser

        webbrowser.open(TOKEN_GUIDE_URL)

    def _apply(self):
        token = self.token_var.get().strip()
        repo = self.repo_var.get().strip()
        if not token:
            messagebox.showwarning("토큰 필요", "GitHub 토큰(PAT)을 입력하세요.")
            return
        if not repo or "/" not in repo:
            messagebox.showwarning("레포 필요", "owner/repo 형식으로 입력하세요.")
            return
        if not self._recipients:
            if not messagebox.askyesno("목록 비어 있음", "수신자가 0명입니다. REPORT_EMAIL을 비우시겠습니까?"):
                return

        self.status_var.set("GitHub에 적용 중...")
        self.update_idletasks()
        try:
            update_report_email_secret(token, repo, self._recipients)
        except Exception as e:
            logger.exception("secret update failed")
            self.status_var.set(f"실패: {e}")
            messagebox.showerror("적용 실패", str(e))
            return
        self._save_local()
        self.status_var.set(
            f"적용 완료: {len(self._recipients)}명의 수신자가 REPORT_EMAIL에 저장되었습니다. 다음 발송부터 반영됩니다."
        )
        messagebox.showinfo("완료", "REPORT_EMAIL 시크릿이 업데이트되었습니다.")


if __name__ == "__main__":
    app = EmailManagerApp()
    app.mainloop()
