// 滚动进入视口的小型 composable（IntersectionObserver，无第三方依赖）。
// 用法：
//   useReveal('.reveal');       // 给所有 .reveal 自动加 is-in
//   useReveal(target, onIn);    // 命中时调 onIn(entry)

import { onMounted, onBeforeUnmount } from 'vue';

export function useReveal(selector: string | string, onIn?: (entry: IntersectionObserverEntry) => void) {
  let io: IntersectionObserver | null = null;
  const els: Element[] = [];

  function bind() {
    const sel = Array.isArray(selector) ? selector.join(',') : selector;
    document.querySelectorAll(sel).forEach((el) => {
      if (el.classList.contains('is-in')) return;
      els.push(el);
      io!.observe(el);
    });
  }

  onMounted(() => {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add('is-in');
          onIn?.(e);
          io!.unobserve(e.target);
        }
      }
    }, { threshold: 0.18 });
    if (reduce) {
      document.querySelectorAll(selector as string).forEach((el) => el.classList.add('is-in'));
    } else {
      bind();
    }
  });

  onBeforeUnmount(() => {
    io?.disconnect();
    els.length = 0;
  });
}