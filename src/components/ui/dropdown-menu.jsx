import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { cn } from "../../lib/utils";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export function DropdownMenuLabel({ className, ...props }) {
  return <DropdownMenuPrimitive.Label className={cn("px-3 pb-1.5 pt-2.5 text-[9px] font-bold uppercase tracking-[0.08em] text-ink-faint", className)} {...props} />;
}

export function DropdownMenuSeparator({ className, ...props }) {
  return <DropdownMenuPrimitive.Separator className={cn("my-1 h-px bg-line", className)} {...props} />;
}

export function DropdownMenuContent({ className, sideOffset = 6, ...props }) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content sideOffset={sideOffset} collisionPadding={10} className={cn("z-50 min-w-48 rounded-[9px] border border-line-strong bg-paper p-1.5 shadow-float data-[state=closed]:animate-out data-[state=open]:animate-in", className)} {...props} />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, children, ...props }) {
  return <DropdownMenuPrimitive.Item className={cn("flex min-h-9 cursor-pointer select-none items-center gap-2 rounded-[6px] px-2.5 py-2 text-[11px] font-semibold outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-selected data-[disabled]:opacity-45", className)} {...props}>{children}</DropdownMenuPrimitive.Item>;
}

export function DropdownMenuCheckboxItem({ className, children, checked, ...props }) {
  return (
    <DropdownMenuPrimitive.CheckboxItem checked={checked} className={cn("relative flex min-h-9 cursor-pointer select-none items-center rounded-[6px] py-2 pl-8 pr-2.5 text-[11px] font-semibold outline-none data-[highlighted]:bg-selected", className)} {...props}>
      <span className="absolute left-2.5"><DropdownMenuPrimitive.ItemIndicator><Check className="size-3.5" /></DropdownMenuPrimitive.ItemIndicator></span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  );
}
