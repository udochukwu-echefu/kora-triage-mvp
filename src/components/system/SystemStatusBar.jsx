import { AlertTriangle, Bot, CloudOff, LoaderCircle, RefreshCw, UserRoundCheck } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";

const statusIcons = {
  connected: Bot,
  degraded: AlertTriangle,
  manual: UserRoundCheck,
  recovering: LoaderCircle,
  offline: CloudOff
};

export function SystemStatusBar({ state, title, description, actionLabel, onAction, affectedCount, compact = false }) {
  const Icon = statusIcons[state] || AlertTriangle;
  return (
    <section
      className={cn("system-status-bar", `system-status-${state}`, compact && "system-status-compact")}
      aria-live={state === "connected" ? "off" : "polite"}
      aria-label={`Operating mode: ${title}`}
    >
      <Icon className={cn("system-status-icon", state === "recovering" && "animate-spin")} aria-hidden="true" />
      <div className="system-status-copy">
        <strong>{title}</strong>
        {description && <p>{description}</p>}
      </div>
      {affectedCount != null && <span className="system-status-count">{affectedCount} affected</span>}
      {actionLabel && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          <RefreshCw className="size-4" />{actionLabel}
        </Button>
      )}
    </section>
  );
}
