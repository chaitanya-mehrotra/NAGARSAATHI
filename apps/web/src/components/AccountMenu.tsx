import { useEffect, useId, useRef, useState } from "react";
import { LogOut, ShieldCheck } from "lucide-react";
import { useI18n } from "../i18n";

type Person = { name: string; email?: string; role: string };

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const letters = words.length === 1 ? [...words[0]].slice(0, 1) : [[...words[0]][0], [...words[words.length - 1]][0]];
  return letters.join("").toUpperCase();
}

const ROLE_KEYS: Record<string, string> = {
  admin: "account.role.admin",
  nigam: "account.role.nigam",
  reviewer: "account.role.nigam",
  operator: "account.role.nigam",
  citizen: "account.role.citizen",
};

/** One avatar button that shows who is signed in (and an admin badge); opens a small menu. */
export function AccountMenu({ user, onSignOut }: { user: Person; onSignOut: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const isAdmin = user.role === "admin";

  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const role = t(ROLE_KEYS[user.role] ?? "account.role.citizen");

  return (
    <div className="account" ref={root}>
      <button
        ref={button}
        type="button"
        className={"account-button" + (isAdmin ? " admin" : "")}
        aria-label={`${t("account.menu")}: ${user.name}, ${role}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title={`${user.name} · ${role}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">{initials(user.name)}</span>
        {isAdmin && (
          <span className="account-badge" aria-hidden="true">
            <ShieldCheck size={11} />
          </span>
        )}
      </button>
      {open && (
        <div className="account-popover" id={menuId} role="menu">
          <div className="account-who">
            <strong>{user.name}</strong>
            {user.email && <span>{user.email}</span>}
            <span className={"account-role" + (isAdmin ? " admin" : "")}>{role}</span>
          </div>
          <button
            type="button"
            role="menuitem"
            className="account-item"
            autoFocus
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            <LogOut size={16} />
            {t("top.signOut")}
          </button>
        </div>
      )}
    </div>
  );
}
