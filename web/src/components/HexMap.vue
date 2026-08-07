<script setup>
import { computed } from "vue";

const props = defineProps({
  bytes: { type: Array, default: () => [] },
  fields: { type: Array, default: () => [] },
  showAscii: { type: Boolean, default: false },
  /** 当前高亮字段（悬停） */
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

const byteByOffset = computed(() => new Map(props.bytes.map((b) => [b.offset, b])));

function asciiText(hex) {
  const code = Number.parseInt(hex, 16);
  if (!Number.isInteger(code) || code < 0 || code > 0xff) return "?";
  if (code === 0x20) return "SP";
  if (code >= 0x21 && code <= 0x7e) return String.fromCharCode(code);
  return `\\x${hex.toUpperCase().padStart(2, "0")}`;
}

function colorClass(offset) {
  const range = highlightRange.value;
  const inHighlight = range && offset >= range[0] && offset < range[1];
  if (inHighlight) return "bg-primary text-inverted ring-2 ring-primary z-10";
  if (props.hoverOffset === offset) return "bg-elevated ring-1 ring-primary";
  const byte = byteByOffset.value.get(offset);
  if (props.showAscii && byte?.hex === "20") {
    return "border border-default bg-muted/35 text-muted";
  }
  const f = fieldByOffset.value.get(offset);
  if (!f) {
    if (byte?.hex === "20") return "border border-default bg-muted/50 text-muted";
    return "border border-warning/30 bg-warning/10 text-warning";
  }
  const map = {
    primary: "border border-primary/30 bg-primary/15 text-primary",
    success: "border border-success/30 bg-success/15 text-success",
    info: "border border-info/30 bg-info/15 text-info",
    warning: "border border-warning/30 bg-warning/15 text-warning",
    error: "border border-error/30 bg-error/15 text-error",
    neutral: "border border-default bg-muted/70 text-toned",
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
        class="w-10 rounded-md flex flex-col items-center justify-center gap-0.5 transition-colors cursor-pointer overflow-hidden"
        :class="[colorClass(b.offset), showAscii ? 'h-11' : 'h-10']"
        @mouseenter="onEnter(b.offset)"
        @click="onClick(b.offset)"
      >
        <span class="text-sm font-semibold tracking-wide">{{ b.hex }}</span>
        <span v-if="showAscii" class="text-[10px] leading-none opacity-75">{{ asciiText(b.hex) }}</span>
      </button>
    </div>
  </div>
</template>
