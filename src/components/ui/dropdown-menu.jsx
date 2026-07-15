import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { cn } from "../../lib/utils";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export function DropdownMenuLabel({ className, ...props }) {
  return <DropdownMenuPrimitive.Label className={cn("px-2.5 py-2 text-[9px] font-extrabold uppercase tracking-[0.1em] text-ink-faint", className)} {...props} />;
}

export function DropdownMenuSeparator({ className, ...props }) {
  return <DropdownMenuPrimitive.Separator className={cn("my-1 h-px bg-line", className)} {...props} />;
}

export function DropdownMenuContent({ className, sideOffset = 6, ...props }) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content sideOffset={sideOffset} className={cn("z-50 min-w-44 border border-line-strong bg-paper p-1 shadow-precision", className)} {...props} />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, children, ...props }) {
  return <DropdownMenuPrimitive.Item className={cn("flex h-9 cursor-pointer select-none items-center gap-2 px-2.5 text-[11px] font-semibold outline-none data-[highlighted]:bg-muted-surface", className)} {...props}>{children}</DropdownMenuPrimitive.Item>;
}

export function DropdownMenuCheckboxItem({ className, children, checked, ...props }) {
  return (
    <DropdownMenuPrimitive.CheckboxItem checked={checked} className={cn("relative flex h-9 cursor-pointer select-none items-center pl-8 pr-2.5 text-[11px] font-semibold outline-none data-[highlighted]:bg-muted-surface", className)} {...props}>
      <span className="absolute left-2.5"><DropdownMenuPrimitive.ItemIndicator><Check className="size-3.5" /></DropdownMenuPrimitive.ItemIndicator></span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  );
}
