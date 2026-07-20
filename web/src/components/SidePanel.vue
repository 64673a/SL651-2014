<script setup>
import { computed, reactive, ref, watch } from "vue";
import { post } from "../api";

const props = defineProps({
  clients: { type: Array, default: () => [] },
  funcCodes: { type: Object, default: () => ({}) },
  rtu: { type: Object, default: null },
  centerPort: { type: [Number, String], default: 9000 },
});
const emit = defineEmits(["refresh"]);
const toast = useToast();

const peer = ref("");
const mode = ref("down");
const down = reactive({
  func_code: "37",
  end_flag: "04",
  remote_addr: "",
  center_addr: "01",
  password: "A000",
  body_hex: "",
});
const hexRaw = ref("");
const preview = ref("");
const parseHex = ref("");
const parseResult = ref("");
const sending = ref(false);

const rtuForm = reactive({
  remote_addr: "0010100001",
  password: "A000",
  heartbeat: 30,
  report: 60,
  water: 12.34,
  rain: 1.5,
  voltage: 12.6,
});
const rtuHex = ref("");
const rtuSending = ref(false);
const rtuMsg = ref("未启动");

const modeItems = [
  { label: "构造下行帧", value: "down" },
  { label: "原始 Hex", value: "hex" },
];

const endItems = [
  { label: "04 EOT", value: "04" },
  { label: "03 ETX", value: "03" },
  { label: "17 ETB", value: "17" },
];

const funcOptions = computed(() => {
  const prefer = ["37", "2F", "32", "33", "4A", "41", "43", "51", "40"];
  const entries = Object.entries(props.funcCodes || {});
  const top = prefer.filter((k) => props.funcCodes[k]).map((k) => [k, props.funcCodes[k]]);
  const rest = entries.filter(([k]) => !prefer.includes(k));
  return [...top, ...rest].map(([code, name]) => ({ label: `${code} ${name}`, value: code }));
});

const peerItems = computed(() =>
  (props.clients || []).map((c) => ({
    label: `${c.peer} (${c.remote_addr || "?"})`,
    value: c.peer,
  }))
);

watch(
  () => props.clients,
  (list) => {
    if (!list?.length) {
      peer.value = "";
      return;
    }
    // 当前选中仍在线：用最新会话信息刷新站址/密码（首次上报后 remote_addr 才有值）
    const cur = list.find((c) => c.peer === peer.value);
    if (cur) {
      fillFromClient(cur);
      return;
    }
    // 选中已断开：自动切到第一个并填入
    peer.value = list[0].peer;
    fillFromClient(list[0]);
  },
  { immediate: true, deep: true }
);

// 目标 peer 下拉切换时，自动填入遥测站址 / 中心站 / 密码
watch(peer, (p) => {
  if (!p) return;
  const c = (props.clients || []).find((x) => x.peer === p);
  if (c) fillFromClient(c);
});

watch(
  () => props.rtu,
  (r) => {
    rtuMsg.value = r?.running
      ? `运行中 · ${r.remote_addr} → ${r.host}:${r.port}`
      : "未启动";
  },
  { immediate: true }
);

function fillFromClient(c) {
  if (!c) return;
  // 仅在有有效值时覆盖，避免空串冲掉已填内容
  if (c.remote_addr) down.remote_addr = c.remote_addr;
  if (c.center_addr) down.center_addr = c.center_addr;
  if (c.password) down.password = c.password;
}

function selectClient(c) {
  peer.value = c.peer;
  fillFromClient(c);
}

async function sendDown() {
  if (!peer.value) {
    toast.add({ title: "请先连接 RTU", color: "warning" });
    return;
  }
  sending.value = true;
  try {
    const r =
      mode.value === "hex"
        ? await post("/api/send", { peer: peer.value, mode: "hex", hex: hexRaw.value })
        : await post("/api/send", { peer: peer.value, mode: "down", ...down });
    if (!r.ok) toast.add({ title: r.error || "发送失败", color: "error" });
    else toast.add({ title: "下行已发送", color: "success" });
  } finally {
    sending.value = false;
  }
}

async function doPreview() {
  // 已展开则折叠
  if (preview.value) {
    preview.value = "";
    return;
  }
  const r = await post("/api/build-down", { ...down });
  preview.value = r.ok ? r.hex + "\n\n" + JSON.stringify(r.parsed, null, 2) : "错误: " + r.error;
}

async function doParse() {
  if (parseResult.value) {
    parseResult.value = "";
    return;
  }
  const r = await post("/api/parse", { hex: parseHex.value });
  parseResult.value = r.ok ? JSON.stringify(r.parsed, null, 2) : "错误: " + r.error;
}

async function rtuStart() {
  const r = await post("/api/rtu/start", {
    ...rtuForm,
    port: Number(props.centerPort) || 9000,
  });
  rtuMsg.value = r.ok ? "启动中..." : "失败: " + r.error;
  toast.add({
    title: r.ok ? "模拟 RTU 已启动" : r.error || "启动失败",
    color: r.ok ? "success" : "error",
  });
  setTimeout(() => emit("refresh"), 800);
}

async function rtuStop() {
  await post("/api/rtu/stop");
  rtuMsg.value = "已停止";
  toast.add({ title: "模拟 RTU 已停止", color: "neutral" });
  emit("refresh");
}

async function rtuSend(kind) {
  const r = await post("/api/rtu/send", {
    kind,
    water: rtuForm.water,
    rain: rtuForm.rain,
    voltage: rtuForm.voltage,
  });
  if (!r.ok) toast.add({ title: r.error || "失败", color: "error" });
  else toast.add({ title: `已发送 ${kind}`, color: "success" });
}

async function rtuSendHex() {
  const hex = (rtuHex.value || "").trim();
  if (!hex) {
    toast.add({ title: "请输入自定义 Hex", color: "warning" });
    return;
  }
  rtuSending.value = true;
  try {
    const r = await post("/api/rtu/send", { kind: "hex", hex });
    if (!r.ok) toast.add({ title: r.error || "发送失败", color: "error" });
    else toast.add({ title: "自定义 Hex 已发送", color: "success" });
  } finally {
    rtuSending.value = false;
  }
}
</script>

<template>
  <aside class="flex flex-col gap-3">
    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-cable" class="size-4 text-primary" />
          <span class="text-sm font-semibold">已连接 RTU</span>
        </div>
      </template>

      <UEmpty v-if="!clients.length" icon="i-lucide-unplug" title="暂无连接" description="等待 RTU 接入 TCP 端口" />
      <div v-else class="flex flex-col gap-2 max-h-44 overflow-auto">
        <UButton
          v-for="c in clients"
          :key="c.peer"
          :variant="peer === c.peer ? 'soft' : 'ghost'"
          :color="peer === c.peer ? 'primary' : 'neutral'"
          class="justify-start"
          block
          @click="selectClient(c)"
        >
          <div class="text-left w-full">
            <div class="font-mono text-xs">{{ c.peer }}</div>
            <div class="text-xs text-muted">站址 {{ c.remote_addr || "-" }} · ↑{{ c.up_count }} ↓{{ c.down_count }}</div>
          </div>
        </UButton>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-send" class="size-4 text-primary" />
          <span class="text-sm font-semibold">下行调试</span>
        </div>
      </template>

      <div class="flex flex-col gap-3">
        <UFormField label="目标 peer">
          <USelect
            v-model="peer"
            :items="peerItems.length ? peerItems : [{ label: '无可用连接', value: '' }]"
            value-key="value"
            class="w-full"
          />
        </UFormField>
        <UFormField label="模式">
          <USelect v-model="mode" :items="modeItems" value-key="value" class="w-full" />
        </UFormField>

        <template v-if="mode === 'down'">
          <!-- 功能码单独一行，避免长名称被截断 -->
          <UFormField label="功能码">
            <USelect
              v-model="down.func_code"
              :items="funcOptions"
              value-key="value"
              class="w-full"
              :ui="{
                base: 'w-full',
                trailing: 'pe-2',
                content: 'min-w-[var(--reka-select-trigger-width)] max-w-[min(90vw,28rem)]',
                itemLabel: 'whitespace-normal break-all',
                value: 'truncate',
              }"
            />
          </UFormField>
          <div class="grid grid-cols-2 gap-2">
            <UFormField label="结束符">
              <USelect v-model="down.end_flag" :items="endItems" value-key="value" class="w-full" />
            </UFormField>
            <UFormField label="中心站">
              <UInput v-model="down.center_addr" placeholder="01" />
            </UFormField>
          </div>
          <UFormField label="遥测站址">
            <UInput v-model="down.remote_addr" placeholder="0010100001" class="w-full" />
          </UFormField>
          <UFormField label="密码">
            <UInput v-model="down.password" />
          </UFormField>
          <UFormField label="正文 Hex">
            <UTextarea
              v-model="down.body_hex"
              :rows="3"
              placeholder="可选"
              class="w-full font-mono text-xs"
              :ui="{ base: 'w-full min-h-[4.5rem]' }"
            />
          </UFormField>
          <div class="flex gap-2">
            <UButton
              color="neutral"
              variant="soft"
              :icon="preview ? 'i-lucide-eye-off' : 'i-lucide-eye'"
              @click="doPreview"
            >
              {{ preview ? "收起预览" : "预览" }}
            </UButton>
            <UButton color="primary" icon="i-lucide-send" :loading="sending" @click="sendDown">发送</UButton>
          </div>
          <UCard v-if="preview" :ui="{ body: 'p-3 max-h-40 overflow-auto' }">
            <pre class="font-mono text-xs whitespace-pre-wrap break-all m-0">{{ preview }}</pre>
          </UCard>
        </template>
        <template v-else>
          <UFormField label="原始 Hex">
            <UTextarea
              v-model="hexRaw"
              :rows="5"
              placeholder="7E7E..."
              class="w-full font-mono text-xs"
              :ui="{ base: 'w-full min-h-[7rem]' }"
            />
          </UFormField>
          <UButton color="primary" icon="i-lucide-send" :loading="sending" @click="sendDown">发送 Hex</UButton>
        </template>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-cpu" class="size-4 text-primary" />
          <span class="text-sm font-semibold">模拟 RTU</span>
        </div>
      </template>

      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-2">
          <UFormField label="站址"><UInput v-model="rtuForm.remote_addr" /></UFormField>
          <UFormField label="密码"><UInput v-model="rtuForm.password" /></UFormField>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <UFormField label="心跳(秒)"><UInput v-model.number="rtuForm.heartbeat" type="number" /></UFormField>
          <UFormField label="定时报(秒)"><UInput v-model.number="rtuForm.report" type="number" /></UFormField>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <UFormField label="水位"><UInput v-model.number="rtuForm.water" type="number" step="0.01" /></UFormField>
          <UFormField label="雨量"><UInput v-model.number="rtuForm.rain" type="number" step="0.1" /></UFormField>
          <UFormField label="电压"><UInput v-model.number="rtuForm.voltage" type="number" step="0.01" /></UFormField>
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton color="primary" icon="i-lucide-play" @click="rtuStart">启动</UButton>
          <UButton color="neutral" variant="soft" icon="i-lucide-square" @click="rtuStop">停止</UButton>
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('heartbeat')">发心跳</UButton>
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('report')">发定时报</UButton>
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('alarm')">发加报</UButton>
        </div>
        <UFormField label="自定义上行 Hex">
          <UTextarea
            v-model="rtuHex"
            :rows="5"
            placeholder="7E7E... 完整帧（含 CRC）"
            class="w-full font-mono text-xs"
            :ui="{ base: 'w-full min-h-[7rem]' }"
          />
        </UFormField>
        <UButton color="primary" icon="i-lucide-send" :loading="rtuSending" @click="rtuSendHex">
          发送 Hex
        </UButton>
        <p class="text-xs text-muted">{{ rtuMsg }}</p>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-binary" class="size-4 text-primary" />
          <span class="text-sm font-semibold">离线解析</span>
        </div>
      </template>
      <div class="flex flex-col gap-3">
        <UTextarea
          v-model="parseHex"
          :rows="4"
          placeholder="粘贴 7E7E... 报文"
          class="w-full font-mono text-xs"
          :ui="{ base: 'w-full min-h-[6rem]' }"
        />
        <UButton
          color="primary"
          :icon="parseResult ? 'i-lucide-chevrons-up' : 'i-lucide-scan-search'"
          @click="doParse"
        >
          {{ parseResult ? "收起" : "解析" }}
        </UButton>
        <UCard v-if="parseResult" :ui="{ body: 'p-3 max-h-48 overflow-auto' }">
          <pre class="font-mono text-xs whitespace-pre-wrap break-all m-0">{{ parseResult }}</pre>
        </UCard>
      </div>
    </UCard>
  </aside>
</template>
