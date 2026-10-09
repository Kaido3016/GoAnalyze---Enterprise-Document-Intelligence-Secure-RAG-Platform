"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ClipboardList,
  FileSearch,
  Files,
  Gauge,
  LayoutDashboard,
  ScrollText,
  Search,
  Settings,
  Sparkles,
  Sprout,
  X
} from "lucide-react";
import { config } from "@/lib/config";
import { cx } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  matchPrefix?: string;
}

interface NavGroup {
  label: string | null;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }]
  },
  {
    label: "Document Intelligence",
    items: [
      { href: "/documents", label: "Documents", icon: Files, matchPrefix: "/documents" },
      { href: "/search", label: "Search", icon: Search },
      { href: "/ai-research", label: "AI Research", icon: Sparkles }
    ]
  },
  {
    label: "Analysis",
    items: [
      { href: "/documents", label: "Document Analysis", icon: FileSearch },
      { href: "/environmental-reviews", label: "Environmental Reviews", icon: Sprout },
      { href: "/cases", label: "Cases", icon: ClipboardList, matchPrefix: "/cases" }
    ]
  },
  {
    label: "Governance",
    items: [{ href: "/audit", label: "Audit Log", icon: ScrollText }]
  },
  {
    label: "System",
    items: [
      { href: "/setup", label: "Setup", icon: Settings },
      { href: "/system", label: "System Health", icon: Activity }
    ]
  }
];

export function Sidebar({
  collapsed,
  mobileOpen,
  onCloseMobile
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const pathname = usePathname();

  function isActive(item: NavItem) {
    const prefix = item.matchPrefix ?? item.href;
    return pathname === item.href || pathname?.startsWith(prefix + "/");
  }

  return (
    <nav
      className={cx("sidebar", collapsed && "collapsed", mobileOpen && "mobileOpen")}
      aria-label="Primary navigation"
    >
      <div className="sidebarBrand">
        <div className="sidebarBrandMark" aria-hidden="true">
          <Gauge size={18} />
        </div>
        <div style={{ flex: 1 }}>
          <strong>{config.appName}</strong>
          <span>{config.appTagline}</span>
        </div>
        <button
          className="mobileMenuButton"
          style={{ display: mobileOpen ? "flex" : undefined }}
          onClick={onCloseMobile}
          aria-label="Close navigation"
        >
          <X size={16} color="var(--shell-ink)" />
        </button>
      </div>

      <div className="sidebarNav">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && <div className="sidebarGroupLabel">{group.label}</div>}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={cx("sidebarLink", isActive(item) && "active")}
                  aria-current={isActive(item) ? "page" : undefined}
                >
                  <Icon />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}
