import { useEffect } from 'react';

/**
 * Reveal-on-scroll, designed so it can NEVER leave content permanently hidden:
 *
 *  1. Content is visible by default. The hidden/animate-in state in CSS is gated
 *     on `html.reveal-on`, which this hook adds as its FIRST action — so a no-JS
 *     render or an early throw leaves everything visible.
 *  2. An IntersectionObserver gives the staggered entrance for gradual scrolling.
 *  3. A document-capture `scroll` sweep catches scrolling in ANY container
 *     (inner overflow scrollers like #home-scroll don't bubble scroll, but
 *     capture-phase listeners on document still receive it) — so instant jumps
 *     (End key, anchor, back/forward restoration, scroll-to-bottom) reveal too.
 *  4. A safety timeout force-reveals anything still hidden after a grace period.
 *
 * Pass `deps` to re-scan when async content adds new `[data-reveal]` nodes.
 */
export function useReveal(deps: unknown[] = []): void {
  useEffect(() => {
    const SEL = '[data-reveal]:not([data-reveal="in"])';
    const remaining = () => Array.from(document.querySelectorAll<HTMLElement>(SEL));
    if (!remaining().length) return;

    const root = document.documentElement;
    root.classList.add('reveal-on'); // arm the CSS hide — JS is confirmed live
    const reveal = (el: Element) => el.setAttribute('data-reveal', 'in');
    const vh = () => window.innerHeight || root.clientHeight;
    const sweep = () => {
      for (const el of remaining()) {
        if (el.getBoundingClientRect().top < vh() * 0.98) reveal(el);
      }
    };

    let io: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver(
        (entries, obs) => {
          for (const e of entries) {
            if (e.isIntersecting || e.boundingClientRect.top < 0) {
              reveal(e.target);
              obs.unobserve(e.target);
            }
          }
        },
        { rootMargin: '0px 0px -8% 0px', threshold: 0.04 },
      );
      remaining().forEach((el) => io!.observe(el));
    }

    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; sweep(); });
    };
    // capture:true → receive scroll from any descendant scroller, not just window.
    document.addEventListener('scroll', onScroll, { capture: true, passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    document.addEventListener('visibilitychange', onScroll);

    sweep(); // catch a restored scroll position present before any event fires
    // Belt-and-braces guarantee: content must never stay hidden, even if the
    // observer/scroll mechanisms miss it (some inner-scroll/embedded contexts
    // don't surface scroll events). A short grace keeps the on-scroll stagger
    // for normal use while ensuring everything is visible quickly regardless.
    const safety = window.setTimeout(() => remaining().forEach(reveal), 1800);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.clearTimeout(safety);
      io?.disconnect();
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
      document.removeEventListener('visibilitychange', onScroll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
