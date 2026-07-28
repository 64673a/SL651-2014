<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { zh_cn } from "@nuxt/ui/locale";
import { connectWs, del, get, post } from "./api";
import MessageList from "./components/MessageList.vue";
import DetailDrawer from "./components/DetailDrawer.vue";
import SidePanel from "./components/SidePanel.vue";
import { formatAnyToDisplay } from "./datetime";

const toast = useToast();

const status = reactive({
  center: { running: false, port: 9000, auto_ack: true },
  clients: [],
  rtu: null,
  func_codes: {},
  stats: { total: 0, by_direction: {}, crc_fail: 0 },
  db: "",
});

const wsOk = ref(false);
const liveMessages = ref([]);
const history = reactive({
  items: [],
  total: 0,
  limit: 30,
  offset: 0,
  loading: false,
});
const filters = reactive({
  direction: "all",
  keyword: "",
  peer: "",
  func_code: "",
  crc_ok: "",
});
const liveFilters = reactive({
  direction: "all",
  peer: "",
});
const selected = ref(null);
const tab = ref("live");
const autoScroll = ref(true);

let unsubWs = null;

/** 本地时间戳 年-月-日 YYYY-MM-DD HH:mm:ss.SSS */
function formatLocalTs(d = new Date()) {
  const p = (n, w = 2) => String(n).padStart(w, "0");
  const base = formatAnyToDisplay(d);
  return `${base}.${p(d.getMilliseconds(), 3)}`;
}

const statsText = computed(() => {
  const s = status.stats || {};
  return {
    total: s.total || 0,
    up: s.by_direction?.up || 0,
    down: s.by_direction?.down || 0,
    crcFail: s.crc_fail || 0,
  };
});

const directionItems = [
  { label: "全部方向", value: "all" },
  { label: "上行", value: "up" },
  { label: "下行", value: "down" },
  { label: "系统", value: "system" },
];

const crcItems = [
  { label: "CRC 全部", value: "" },
  { label: "CRC 通过", value: "1" },
  { label: "CRC 失败", value: "0" },
];

const funcItems = computed(() => [
  { label: "全部功能码", value: "" },
  ...Object.entries(status.func_codes || {}).map(([code, name]) => ({
    label: `${code} ${name}`,
    value: code,
  })),
]);

const tabItems = [
  { label: "实时流", value: "live", icon: "i-lucide-radio" },
  { label: "历史查询", value: "history", icon: "i-lucide-database" },
];

const page = computed({
  get: () => Math.floor(history.offset / history.limit) + 1,
  set: (p) => {
    history.offset = (p - 1) * history.limit;
    loadHistory();
  },
});

async function refreshStatus() {
  try {
    const data = await get("/api/status");
    Object.assign(status, data);
  } catch (e) {
    console.warn(e);
  }
}

async function loadHistory(reset = false) {
  if (reset) history.offset = 0;
  history.loading = true;
  try {
    const q = new URLSearchParams({
      limit: String(history.limit),
      offset: String(history.offset),
    });
    if (filters.direction && filters.direction !== "all") q.set("direction", filters.direction);
    if (filters.keyword) q.set("keyword", filters.keyword);
    if (filters.peer) q.set("peer", filters.peer);
    if (filters.func_code) q.set("func_code", filters.func_code);
    if (filters.crc_ok === "1") q.set("crc_ok", "true");
    if (filters.crc_ok === "0") q.set("crc_ok", "false");
    const data = await get(`/api/messages?${q}`);
    history.items = data.items || [];
    history.total = data.total || 0;
  } catch (e) {
    console.warn(e);
  } finally {
    history.loading = false;
  }
}

function handleEvent(msg) {
  if (msg.type === "snapshot") {
    // 实时流不回填历史：刷新/重连后默认空列表，只显示之后新到的报文
    // 历史数据在「历史查询」Tab 从 SQLite 拉取
    status.clients = msg.data.clients || [];
    if (msg.data.status) Object.assign(status.center, msg.data.status);
    if (msg.data.stats) status.stats = msg.data.stats;
    return;
  }
  if (msg.type === "message") {
    const m = msg.data;
    // 最新在上方：新消息插入到数组头部
    liveMessages.value.unshift(m);
    if (liveMessages.value.length > 300) liveMessages.value.pop();
    status.stats.total = (status.stats.total || 0) + 1;
    const dir = m.direction;
    if (dir) {
      status.stats.by_direction = status.stats.by_direction || {};
      status.stats.by_direction[dir] = (status.stats.by_direction[dir] || 0) + 1;
    }
    if (m.crc_ok === false) status.stats.crc_fail = (status.stats.crc_fail || 0) + 1;
    return;
  }
  if (msg.type === "clients") {
    status.clients = msg.data || [];
    return;
  }
  if (msg.type === "system") {
    liveMessages.value.unshift({
      id: "sys-" + Date.now(),
      // 本地时区（北京时间），勿用 toISOString（UTC）
      ts: formatLocalTs(),
      direction: "system",
      peer: "-",
      raw_hex: "",
      note: typeof msg.data === "object" ? msg.data.msg || JSON.stringify(msg.data) : String(msg.data),
    });
    if (liveMessages.value.length > 300) liveMessages.value.pop();
    refreshStatus();
  }
}

function clearLiveMessages() {
  liveMessages.value = [];
  selected.value = null;
  toast.add({ title: "已清空当前实时列表", color: "neutral" });
}

async function clearDbMessages() {
  if (!confirm("确认清空库内全部历史报文？此操作不可恢复。")) return;
  const r = await del("/api/messages?scope=db");
  await loadHistory(true);
  await refreshStatus();
  toast.add({
    title: `已清空库内历史（${r.deleted ?? 0} 条）`,
    color: "success",
  });
}

async function toggleAutoAck(val) {
  await post("/api/center/config", { auto_ack: val });
  status.center.auto_ack = val;
  toast.add({ title: `自动应答 ${val ? "已开启" : "已关闭"}`, color: "neutral" });
}

watch(
  () => [filters.direction, filters.keyword, filters.peer, filters.func_code, filters.crc_ok],
  () => {
    if (tab.value === "history") loadHistory(true);
  }
);

watch(tab, (v) => {
  if (v === "history") loadHistory(true);
});

onMounted(() => {
  refreshStatus();
  unsubWs = connectWs(handleEvent, (ok) => (wsOk.value = ok));
});

onUnmounted(() => unsubWs?.());
</script>

<template>
  <!-- scroll-body=false：弹窗不锁 body/不补 padding，避免列表横向跳动 -->
  <UApp :locale="zh_cn" :scroll-body="false">
    <!-- 占满视口，去掉底部空白；整页不滚，左右各自滚 -->
    <div class="h-dvh flex flex-col overflow-hidden bg-default">
      <header class="shrink-0 z-20 border-b border-default bg-default">
        <div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div class="flex items-center gap-3">
            <div class="flex size-10 items-center justify-center rounded-xl bg-primary text-inverted font-bold text-lg">
              ◈
            </div>
            <div>
              <h1 class="text-base font-semibold text-highlighted">SL651-2014 水文协议调试助手</h1>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
            <!-- 连接性：中心站 + WS -->
            <div class="flex flex-wrap items-center gap-2">
              <UBadge
                :color="status.center.running ? 'success' : 'error'"
                variant="subtle"
                :label="`中心站 :${status.center.port || '-'}`"
              />
              <UBadge
                :color="wsOk ? 'success' : 'error'"
                variant="subtle"
                :label="wsOk ? 'WS 已连接' : 'WS 断开'"
              />
            </div>

            <!-- 计数：RTU + 库内（紧凑文字标签，不再是 6 药丸墙） -->
            <div class="flex items-center gap-2 text-xs text-muted">
              <span>RTU <span class="font-medium text-highlighted">{{ status.clients.length }}</span></span>
              <span class="text-muted">·</span>
              <span>库内 <span class="font-medium text-highlighted">{{ statsText.total }}</span></span>
              <!-- CRC 失败仅 >0 时显示，避免常态噪声 -->
              <template v-if="statsText.crcFail">
                <span class="text-muted">·</span>
                <span class="text-warning">CRC失败 {{ statsText.crcFail }}</span>
              </template>
            </div>

            <!-- 开关 + 主题 -->
            <div class="flex items-center gap-2 pl-1">
              <USwitch
                :model-value="status.center.auto_ack"
                size="sm"
                @update:model-value="toggleAutoAck"
              />
              <span class="text-xs text-muted">自动应答</span>
            </div>
            <UColorModeButton />
          </div>
        </div>
      </header>

      <main class="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[480px_minmax(0,1fr)] gap-3 p-3 overflow-hidden">
        <!-- 左：控制面板独立滚动 -->
        <div class="min-h-0 overflow-y-auto overscroll-contain pr-0.5">
          <SidePanel
            :clients="status.clients"
            :func-codes="status.func_codes"
            :rtu="status.rtu"
            :center-port="status.center.port"
            @refresh="refreshStatus"
          />
        </div>

        <!-- 右：工具条固定 + 报文列表独立滚动 -->
        <div class="min-h-0 min-w-0 flex flex-col overflow-hidden rounded-xl border border-default bg-default">
          <div class="shrink-0 border-b border-default px-3 py-2">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <UTabs v-model="tab" :items="tabItems" :content="false" size="sm" class="w-auto" />
              <div class="flex flex-wrap items-center gap-2">
                <template v-if="tab === 'live'">
                  <UInput
                    v-model="liveFilters.peer"
                    icon="i-lucide-network"
                    placeholder="按 IP / peer 筛选"
                    class="w-40"
                    size="sm"
                  />
                  <USelect
                    v-model="liveFilters.direction"
                    :items="directionItems"
                    value-key="value"
                    class="w-32"
                    size="sm"
                  />
                  <div class="flex items-center gap-2">
                    <USwitch v-model="autoScroll" size="sm" />
                    <span class="text-xs text-muted">自动滚动</span>
                  </div>
                  <UButton color="neutral" variant="soft" size="sm" icon="i-lucide-eraser" @click="clearLiveMessages">
                    清空当前
                  </UButton>
                </template>
                <template v-else>
                  <UInput
                    v-model="filters.peer"
                    icon="i-lucide-network"
                    placeholder="按 IP / peer"
                    class="w-36"
                    size="sm"
                  />
                  <UInput
                    v-model="filters.keyword"
                    icon="i-lucide-search"
                    placeholder="hex / 站址 / 备注"
                    class="w-40"
                    size="sm"
                  />
                  <USelect
                    v-model="filters.direction"
                    :items="directionItems.filter((i) => i.value !== 'system')"
                    value-key="value"
                    class="w-28"
                    size="sm"
                  />
                  <USelect v-model="filters.crc_ok" :items="crcItems" value-key="value" class="w-32" size="sm" />
                  <USelect
                    v-model="filters.func_code"
                    :items="funcItems"
                    value-key="value"
                    class="w-44"
                    size="sm"
                  />
                  <UButton color="error" variant="soft" size="sm" icon="i-lucide-trash-2" @click="clearDbMessages">
                    清空库内
                  </UButton>
                </template>
              </div>
            </div>
          </div>

          <div class="flex-1 min-h-0 overflow-hidden flex flex-col">
            <MessageList
              v-if="tab === 'live'"
              :messages="liveMessages"
              :direction="liveFilters.direction"
              :peer="liveFilters.peer"
              :auto-scroll="autoScroll && !selected"
              @select="selected = $event"
            />
            <template v-else>
              <MessageList
                :messages="history.items"
                direction="all"
                :auto-scroll="false"
                @select="selected = $event"
              />
              <div class="shrink-0 flex items-center justify-between px-3 py-2 border-t border-default">
                <span class="text-sm text-muted">共 {{ history.total }} 条</span>
                <UPagination v-model:page="page" :total="history.total" :items-per-page="history.limit" size="sm" />
              </div>
            </template>
          </div>
        </div>
      </main>

      <DetailDrawer :message="selected" @close="selected = null" />
    </div>
  </UApp>
</template>
