import { useState } from "react";
import {
  Activity, ArrowRight, Bell, BellRing, CheckCheck, CheckCircle2, ChevronDown, CircleUserRound,
  Inbox, LogOut, Menu, Moon, Sun, Timer, UserRoundCheck
} from "lucide-react";
import { cn } from "../lib/utils";
import { formatRelative, initialsOf, intentShort, isProcessed, operationalState, slaState, urgencyOrder } from "../lib/tickets";
import { Button } from "../components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger
} from "../components/ui/dropdown-menu";

const titles = {
  queue: { full: "Queue", compact: "Queue" },
  insights: { full: "Insights", compact: "Insights" },
  proof: { full: "Historical evaluation", compact: "Evaluation" },
  audit: { full: "Decision audit", compact: "Audit" },
  team: { full: "Team coverage", compact: "Team" },
  settings: { full: "Confidence automation", compact: "Automation" }
};

const notificationPeriods = [
  { id: "today", label: "Today" },
  { id: "week", label: "This week" },
  { id: "earlier", label: "Earlier" }
];

export default function Header({ activeView, onMenu, backend, tickets, now, onOpenTicket, onView, onLogout, user, theme, onThemeToggle }) {
  const [readNotificationIds, setReadNotificationIds] = useState([]);
  const [notificationPeriod, setNotificationPeriod] = useState("today");
  const displayName = user?.display_name || "Account";
  const role = (user?.role || "").replaceAll("_", " ");
  const engineLabel = backend.state === "checking"
    ? "Checking API"
    : backend.configured
      ? "AI service available"
      : backend.state === "online" ? "AI setup required" : "AI service unavailable";
  const notifications = tickets
    .filter((ticket) => ticket.lifecycle?.state !== "resolved")
    .sort((a, b) => Number(b.escalated) - Number(a.escalated) || urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || a.minutesAgo - b.minutesAgo)
    .map((ticket) => ({
      ...ticket,
      notificationTitle: ticket.escalated ? "Human review required" : isProcessed(ticket) ? `${intentShort[ticket.intent] || ticket.intent} triaged` : "Live triage pending"
    }));
  const unreadCount = notifications.filter((notification) => !readNotificationIds.includes(notification.id)).length;
  const periodFor = (notification) => notification.minutesAgo < 1440 ? "today" : notification.minutesAgo < 10080 ? "week" : "earlier";
  const visibleNotifications = notifications.filter((notification) => periodFor(notification) === notificationPeriod).slice(0, 5);
  return (
    <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-line bg-paper px-4 sm:px-7 lg:px-8">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Button variant="outline" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation"><Menu className="size-4" /></Button>
        <h1 className="truncate text-[18px] font-semibold tracking-[-0.035em] sm:text-[20px]"><span className="sm:hidden">{titles[activeView].compact}</span><span className="hidden sm:inline">{titles[activeView].full}</span></h1>
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden items-center gap-2 rounded-[12px] border border-line px-3 py-2 text-xs font-bold text-ink-muted sm:flex"><span className={cn("size-2 rounded-full", backend.configured ? "bg-accent" : "bg-line-strong")} />{engineLabel}</div>
        <Button variant="outline" size="icon" onClick={onThemeToggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`} className="relative">
              <Bell className="size-4" />
              {unreadCount > 0 && <span className="absolute right-0.5 top-0.5 grid size-5 place-items-center rounded-full bg-accent text-xs font-extrabold text-accent-ink">{unreadCount > 99 ? "99+" : unreadCount}</span>}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="notification-popover w-[min(400px,calc(100vw-20px))] p-0" sideOffset={9}>
            <div className="notification-header">
              <div className="flex items-center gap-3">
                <span className="notification-header-icon"><BellRing className="size-4" /></span>
                <div><p className="text-[16px] font-semibold tracking-[-0.025em]">Notifications</p><p className="mt-0.5 text-xs text-ink-faint">Open conversations by priority</p></div>
              </div>
              <DropdownMenuItem onSelect={() => onView("queue")} className="notification-see-all">See all<ArrowRight className="size-3.5" /></DropdownMenuItem>
            </div>
            <div className="notification-tabs" role="tablist" aria-label="Notification period">
              {notificationPeriods.map((period) => {
                const count = notifications.filter((notification) => periodFor(notification) === period.id).length;
                return <button key={period.id} type="button" role="tab" aria-selected={notificationPeriod === period.id} className={cn(notificationPeriod === period.id && "is-active")} onClick={() => setNotificationPeriod(period.id)}>{period.label}<span>{count}</span></button>;
              })}
            </div>
            <div className="notification-list max-h-[430px] overflow-y-auto" role="tabpanel">
              {visibleNotifications.length ? visibleNotifications.map((notification) => {
                const isRead = readNotificationIds.includes(notification.id);
                const sla = slaState(notification, now);
                return (
                  <DropdownMenuItem
                    key={notification.id}
                    onSelect={() => { setReadNotificationIds((ids) => ids.includes(notification.id) ? ids : [...ids, notification.id]); onOpenTicket(notification.id); }}
                    className={cn("notification-item", isRead && "notification-item-read")}
                  >
                    <span className={cn("notification-symbol", notification.escalated ? "notification-symbol-review" : sla ? "notification-symbol-sla" : "notification-symbol-update")}>
                      {notification.escalated ? <UserRoundCheck className="size-4" /> : sla ? <Timer className="size-4" /> : isProcessed(notification) ? <CheckCircle2 className="size-4" /> : <Bell className="size-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0"><strong className="block truncate text-sm">{notification.notificationTitle}</strong><span className="mt-1 block truncate text-xs text-ink-faint">{notification.customer.name} · {notification.id}</span></span>
                        {!isRead && <span className="mt-1 size-2 shrink-0 rounded-full bg-accent-strong" aria-label="Unread" />}
                      </span>
                      <span className="mt-1.5 block text-[12px] leading-[1.5] text-ink-muted">{intentShort[notification.intent] || notification.intent} · <span className="capitalize">{notification.urgency} urgency</span></span>
                      <span className="mt-2 flex items-center gap-2 text-[12px] text-ink-faint">
                        <span>{sla ? `SLA: ${sla.label}` : `Waiting ${formatRelative(notification.minutesAgo)}`}</span><span className="ml-auto font-semibold">{operationalState(notification) === "pending" ? "Awaiting triage" : operationalState(notification)}</span>
                      </span>
                    </span>
                  </DropdownMenuItem>
                );
              }) : (
                <div className="grid min-h-44 place-items-center px-8 text-center"><div><Bell className="mx-auto size-5 text-ink-faint" /><strong className="mt-3 block text-sm">No updates for this period</strong><p className="mt-1 text-[13px] leading-5 text-ink-faint">New triage decisions and human reviews will appear here.</p></div></div>
              )}
            </div>
            <div className="notification-footer"><span>{unreadCount ? `${unreadCount} unread` : "You're all caught up"}</span><button type="button" onClick={() => setReadNotificationIds(notifications.map((notification) => notification.id))} disabled={!unreadCount} className="notification-mark-read"><CheckCheck className="size-3.5" />Mark all read</button></div>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="px-2.5 sm:px-3" aria-label="Open profile menu">
              <span className="grid size-7 place-items-center rounded-full bg-accent text-xs font-extrabold text-accent-ink sm:hidden">{initialsOf(displayName)}</span>
              <CircleUserRound className="hidden size-4 sm:block" /><span className="hidden sm:inline">{displayName}</span><ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56" sideOffset={8}>
            <div className="px-3 py-3"><p className="text-[14px] font-extrabold">{displayName}</p><p className="mt-1 capitalize text-[12px] font-semibold text-ink-muted">{role}{user?.auth_mode === "demo" ? " · demo" : ""}</p></div>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Workspace</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => onView("queue")}><Inbox className="size-3.5" />Support queue</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onView("audit")}><Activity className="size-3.5" />Audit trail</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onLogout} className="text-ink"><LogOut className="size-3.5" />Log out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
