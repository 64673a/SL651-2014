<script setup>
import { computed } from "vue";

const props = defineProps({
  bytes: { type: Array, default: () => [] },
  fields: { type: Array, default: () => [] },
  /** 当前高亮字段（悬停优先，否则为点击锁定） */
  highlightId: { type: String, default: null },
  hoverOffset: { type: Number, default: null },
});
const emit = defineEmits(["hover-byte", "leave", "click-field"]);

const highlightRange = computed(() => {
  if (!props.highlightId) return null;
  const f = props.fields.find((x) => x.id === props.highlightId);
  if (!f) return null;
  return [f.start, f.end];
});

const fieldByOffset = computed(() => {
  const map = new Map();
  for (const f of props.fields) {
    for (let i = f.start; i < f.end; i++) {
      if (!map.has(i)) map.set(i, f);
    }
  }
  return map;
});

function colorClass(offset) {
  const range = highlightRange.value;
  const inHighlight = range && offset >= range[0] && offset < range[1];
  if (inHighlight) return "bg-primary text-inverted ring-2 ring-primary z-10";
  if (props.hoverOffset === offset) return "bg-elevated ring-1 ring-primary";
  const f = fieldByOffset.value.get(offset);
  if (!f) return "bg-muted/30 text-muted";
  const map = {
    primary: "bg-primary/15 text-primary",
    success: "bg-success/15 text-success",
    info: "bg-info/15 text-info",
    warning: "bg-warning/15 text-warning",
    error: "bg-error/15 text-error",
    neutral: "bg-muted/40 text-toned",
  };
  return map[f.color] || map.neutral;
}

function onEnter(offset) {
  emit("hover-byte", offset);
}

function onClick(offset) {
  const f = fieldByOffset.value.get(offset);
  if (f) emit("click-field", f.id);
}

function onLeave() {
  emit("leave");
}
</script>

<template>
  <div class="font-mono leading-none select-none" @mouseleave="onLeave">
    <div class="flex flex-wrap gap-1.5">
      <button
        v-for="b in bytes"
        :key="b.offset"
        type="button"
        class="w-10 h-11 rounded-md flex flex-col items-center justify-center gap-0.5 transition-colors cursor-pointer overflow-hidden"
        :class="colorClass(b.offset)"
        :title="`[${b.offset}] ${b.hex}`"
        @mouseenter="onEnter(b.offset)"
        @click="onClick(b.offset)"
      >
        <span class="text-sm font-semibold tracking-wide">{{ b.hex }}</span>
        <span class="text-[10px] leading-none opacity-55 tabular-nums">{{ b.offset }}</span>
      </button>
    </div>
  </div>
</template>
