import { useEffect, useLayoutEffect, useRef, useState } from "react";

const MENU_GAP_PX = 4;
const VIEWPORT_MARGIN_PX = 8;
// One row of such a menu
export const MENU_ITEM =
  "flex min-h-8 w-full cursor-pointer items-center gap-2 rounded-sm px-2 text-left text-sm font-medium whitespace-nowrap hover:bg-accent";

// A raised menu that lives in body (outside the sidebar's scroll clip), placed right of its button
// with top edges aligned; it flips left or shifts up when the viewport has no room, and closes on a
// press outside, on Escape, or when the page scrolls or resizes under it
export function useAnchoredMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    const menu = menuRef.current;
    if (!isOpen || !trigger || !menu) return;
    const anchor = trigger.getBoundingClientRect();
    const right = anchor.right + MENU_GAP_PX;
    const fitsRight = right + menu.offsetWidth <= window.innerWidth - VIEWPORT_MARGIN_PX;
    setPosition({
      top: Math.max(VIEWPORT_MARGIN_PX, Math.min(anchor.top, window.innerHeight - VIEWPORT_MARGIN_PX - menu.offsetHeight)),
      left: Math.max(VIEWPORT_MARGIN_PX, fitsRight ? right : anchor.left - MENU_GAP_PX - menu.offsetWidth),
    });
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const close = () => setIsOpen(false);
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) close();
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [isOpen]);

  return { isOpen, setIsOpen, position, triggerRef, menuRef };
}
