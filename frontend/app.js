/* ============================================
   我的自由指南灯 · 主控
   [POS] frontend/app.js — UI 状态机 + API 网关 + 仪式编排
   [INPUT] window.LifeGrid · backend REST
   [PROTOCOL] 接口契约见 设计方案.md §4
   ============================================ */

(() => {
  'use strict';

  const API = '/api';
  const $ = (sel) => document.querySelector(sel);
  const fmtCNY = (n) => '¥' + Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  const fmtSignedCNY = (n) => `${Number(n || 0) < 0 ? '−' : '+'}${fmtCNY(Math.abs(Number(n || 0)))}`;
  const fmtInt = (n) => Number(n || 0).toLocaleString('zh-CN');
  const todayISO = () => new Date().toISOString().slice(0, 10);
  const SOURCE_LABELS = {
    family_support: '家庭生活费',
    scholarship: '奖学金 / 助学金',
    part_time: '兼职 / 实习',
    project: '个人项目 / 创作',
    investment: '投资所得',
    other: '其他自主收入',
  };
  const CATEGORY_LABELS = {
    food: '餐饮', transport: '交通', study: '学习', housing: '住宿', medical: '医疗',
    entertainment: '娱乐', social: '社交', digital: '数字服务', other: '其他',
  };
  const ACCOUNT_TYPE_LABELS = {
    bank: '银行卡', wechat: '微信', alipay: '支付宝', campus: '校园卡', cash: '现金', other: '其他',
  };
  const ACTIVITY_LABELS = { strength: '力量', cardio: '有氧', sport: '运动', mobility: '拉伸', other: '活动' };
  const MEAL_LABELS = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' };
  const RHYTHM_CATEGORY_LABELS = { personal: '个人', study: '学习', health: '身体', finance: '财务', other: '其他' };
  const TASK_PRIORITY_LABELS = { low: '低', normal: '普通', high: '高' };
  const LIFE_MODULE_LABELS = {
    finance: '账', fitness: '动', nutrition: '食', recovery: '眠',
    study: '学', rhythm: '律', reflection: '记', goals: '标',
  };
  const LIFE_MODULE_NAMES = {
    finance: '个人账本', fitness: '健身', nutrition: '饮食', recovery: '恢复',
    study: '学习', rhythm: '节奏', reflection: '复盘', goals: '目标',
  };
  const LIFE_SEARCH_KIND_LABELS = { fact: '生活事实', arrangement: '生活安排', reference: '长期条目' };
  const GOAL_CATEGORY_LABELS = { personal: '个人', study: '学习', health: '身体', finance: '财务能力', other: '其他' };
  const GOAL_STATUS_LABELS = { active: '进行中', paused: '已暂停', completed: '已完成' };

  // ---------- API client ----------
  const api = {
    state:    () => fetch(`${API}/state`).then(r => r.json()),
    settings: (body) => post(`${API}/settings`, body),
    addTx:    (body) => post(`${API}/transactions`, body),
    addAccount: (body) => post(`${API}/accounts`, body),
    transfer: (body) => post(`${API}/transfers`, body),
    savePlan: (body) => post(`${API}/planning/settings`, body),
    saveSemester: (body) => post(`${API}/planning/semester`, body),
    quickParse: (body) => post(`${API}/quick/parse`, body),
    quickCommit: (body) => post(`${API}/quick/commit`, body),
    calendar: () => fetch(`${API}/calendar`).then(r => r.json()),
    annualReport: (year) => fetch(`${API}/reports/annual?year=${encodeURIComponent(year)}`).then(r => r.json()),
    searchTransactions: async (params = {}) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== '' && value != null) query.set(key, value);
      });
      const response = await fetch(`${API}/search/transactions?${query}`);
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    exportBackup: () => fetch(`${API}/backup/export`).then(r => r.json()),
    restoreBackup: (body) => post(`${API}/backup/restore`, body),
    addWorkout: (body) => post(`${API}/fitness/sessions`, body),
    addNutrition: (body) => post(`${API}/nutrition/entries`, body),
    saveRecovery: (body) => post(`${API}/recovery/checkin`, body),
    addStudy: (body) => post(`${API}/study/sessions`, body),
    addTask: (body) => post(`${API}/tasks`, body),
    toggleTask: (id) => post(`${API}/tasks/${id}/toggle`, {}),
    addHabit: (body) => post(`${API}/habits`, body),
    toggleHabit: (id, body) => post(`${API}/habits/${id}/toggle`, body),
    reflection: (date) => fetch(`${API}/reflection?date=${encodeURIComponent(date)}`).then(async r => {
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      return r.json();
    }),
    saveReflection: (body) => post(`${API}/reflections`, body),
    lifeCalendar: (month = '', date = '') => {
      const params = new URLSearchParams();
      if (month) params.set('month', month);
      if (date) params.set('date', date);
      return fetch(`${API}/life-calendar?${params}`).then(async r => {
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        return r.json();
      });
    },
    lifeSearch: (params = {}) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== '' && value != null) query.set(key, value);
      });
      return fetch(`${API}/life-search?${query}`).then(async r => {
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        return r.json();
      });
    },
    addLifeGoal: (body) => post(`${API}/life-goals`, body),
    setLifeGoalStatus: (id, status) => post(`${API}/life-goals/${id}/status`, { status }),
    addGoalMilestone: (id, body) => post(`${API}/life-goals/${id}/milestones`, body),
    toggleGoalMilestone: (id) => post(`${API}/goal-milestones/${id}/toggle`, {}),
    addBill: (body) => post(`${API}/bills`, body),
    payBill: (id, body) => post(`${API}/bills/${id}/pay`, body),
    saveBudgets: (body) => post(`${API}/budgets/categories`, body),
    addGoal: (body) => post(`${API}/goals`, body),
    importTransactions: (body) => post(`${API}/import/transactions`, body),
    goalProgress: (id, body) => post(`${API}/goals/${id}/progress`, body),
    delTransfer: async (id) => {
      const response = await fetch(`${API}/transfers/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    reconcile: (accountId, body) => post(`${API}/accounts/${accountId}/reconcile`, body),
    delGoal: async (id) => {
      const response = await fetch(`${API}/goals/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delImportBatch: async (id) => {
      const response = await fetch(`${API}/import/batches/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delBill: async (id) => {
      const response = await fetch(`${API}/bills/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    unpayBill: async (id, month) => {
      const response = await fetch(`${API}/bills/${id}/payments/${month}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delTx:    (id) => fetch(`${API}/transactions/${id}`, { method: 'DELETE' }).then(r => r.json()),
    previewStatement: (body) => post(`${API}/statements/preview`, body),
    focusState: () => fetch(`${API}/study/focus`).then(r => r.json()),
    startFocus: (body) => post(`${API}/study/focus`, body),
    finishFocus: (id, body) => post(`${API}/study/focus/${id}/finish`, body),
    bodyState: () => fetch(`${API}/body`).then(r => r.json()),
    saveBody: (body) => post(`${API}/body/measurements`, body),
    delBody: async (id) => {
      const response = await fetch(`${API}/body/measurements/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    trainingState: () => fetch(`${API}/training`).then(r => r.json()),
    addExercise: (body) => post(`${API}/training/exercises`, body),
    addSet: (body) => post(`${API}/training/sets`, body),
    delSet: async (id) => {
      const response = await fetch(`${API}/training/sets/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    inboxState: () => fetch(`${API}/inbox`).then(r => r.json()),
    addInbox: (body) => post(`${API}/inbox`, body),
    fileInbox: (id, body) => post(`${API}/inbox/${id}/file`, body),
    dropInbox: (id) => post(`${API}/inbox/${id}/drop`, {}),
    insights: (days) => fetch(`${API}/insights?days=${days}`).then(r => r.json()),
    dataHealth: () => fetch(`${API}/insights/health`).then(r => r.json()),
    tagOverview: () => fetch(`${API}/tags/overview`).then(r => r.json()),
    cleanupTags: () => post(`${API}/tags/cleanup`, {}),
    previewHealth: (body) => post(`${API}/health-import/preview`, body),
    commitHealth: (body) => post(`${API}/health-import/commit`, body),
    confirmCapture: (id, body) => post(`${API}/capture/${id}/confirm`, body),
    dismissCapture: (id) => post(`${API}/capture/${id}/dismiss`, {}),
    delWorkout: async (id) => {
      const response = await fetch(`${API}/fitness/sessions/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delNutrition: async (id) => {
      const response = await fetch(`${API}/nutrition/entries/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delRecovery: async (id) => {
      const response = await fetch(`${API}/recovery/checkins/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delStudy: async (id) => {
      const response = await fetch(`${API}/study/sessions/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delTask: async (id) => {
      const response = await fetch(`${API}/tasks/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    archiveHabit: async (id) => {
      const response = await fetch(`${API}/habits/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delReflection: async (id) => {
      const response = await fetch(`${API}/reflections/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delLifeGoal: async (id) => {
      const response = await fetch(`${API}/life-goals/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
    delGoalMilestone: async (id) => {
      const response = await fetch(`${API}/goal-milestones/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return response.json();
    },
  };
  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  }

  // ---------- 全局 state ----------
  const state = {
    settings: null,
    stats: { total_income: 0, total_expense: 0, tracking_days: 0, avg_daily_expense: 0,
             freedom_days_bought: 0, total_cells: 0, lit_count: 0, overflow: 0 },
    transactions: [],
    accounts: [],
    monthly: null,
    transfers: [],
    planning: { settings: {}, goals: [], forecast: {} },
    importPreview: null,
    statementPreview: null,
    importBatches: [],
    calendar: { bills: [], summary: {}, review: {} },
    today: {},
    life: {},
    fitness: { today: {}, week: {}, recent: [] },
    nutrition: { today: {}, recent: [] },
    recovery: { today: null, latest: null, week: {}, recent: [] },
    study: { today: {}, week: {}, recent: [] },
    rhythm: { tasks: [], task_summary: {}, habits: [], habit_summary: {} },
    reflection: { date: '', selected: null, weekly: {}, recent: [] },
    lifeCalendar: { month: '', selected_date: '', days: [], summary: {}, selected: {} },
    goals: { goals: [], summary: {} },
    capture: { pending: [], summary: {}, channel_labels: {} },
    body: { latest: null, changes: {}, recent: [], girth_labels: {} },
    focus: { running: null, today: {}, recent: [] },
    training: { exercises: [], recent_sessions: [], week: {}, records: [] },
    inbox: { items: [], summary: {}, targets: {} },
    insights: null,
    dataHealth: null,
    tagOverview: null,
    healthImportPreview: null,
    lifeSearch: { query: '', results: [], summary: { total: 0 }, truncated: false },
    quickPreview: null,
    annualReport: null,
    searchResult: { transactions: [], summary: { count: 0, income: 0, expense: 0, net: 0 } },
    restoreSnapshot: null,
    txType: 'income',
    txSource: 'family_support',
    currentView: 'today',
    currentModule: 'overview',
    busy: false,
  };

  // ---------- 引用 ----------
  const els = {
    moduleNav: document.querySelectorAll('[data-module-target]'),
    modulePanels: document.querySelectorAll('[data-module-panel]'),
    moduleJumps: document.querySelectorAll('[data-module-jump]'),
    lifeDate: $('#life-date'),
    lifeHeadline: $('#life-headline'),
    lifeCompleted: $('#life-completed'),
    lifeBalance: $('#life-balance'),
    lifeFinanceNote: $('#life-finance-note'),
    lifeFitnessMinutes: $('#life-fitness-minutes'),
    lifeFitnessNote: $('#life-fitness-note'),
    lifeMealCount: $('#life-meal-count'),
    lifeNutritionNote: $('#life-nutrition-note'),
    lifeSleepHours: $('#life-sleep-hours'),
    lifeRecoveryNote: $('#life-recovery-note'),
    lifeStudyMinutes: $('#life-study-minutes'),
    lifeStudyNote: $('#life-study-note'),
    lifeRhythmProgress: $('#life-rhythm-progress'),
    lifeRhythmNote: $('#life-rhythm-note'),
    lifeActions: $('#life-actions'),

    fitnessTodayMinutes: $('#fitness-today-minutes'),
    fitnessTodayCount: $('#fitness-today-count'),
    fitnessWeekMinutes: $('#fitness-week-minutes'),
    fitnessWeekCount: $('#fitness-week-count'),
    fitnessWeekIntensity: $('#fitness-week-intensity'),
    fitnessActivity: $('#fitness-activity'),
    fitnessDate: $('#fitness-date'),
    fitnessDuration: $('#fitness-duration'),
    fitnessIntensity: $('#fitness-intensity'),
    fitnessIntensityOutput: $('#fitness-intensity-output'),
    fitnessNote: $('#fitness-note'),
    btnAddWorkout: $('#btn-add-workout'),
    fitnessStatus: $('#fitness-status'),
    fitnessList: $('#fitness-list'),

    nutritionTodayCount: $('#nutrition-today-count'),
    nutritionCalories: $('#nutrition-calories'),
    nutritionCaloriesNote: $('#nutrition-calories-note'),
    nutritionProtein: $('#nutrition-protein'),
    nutritionWater: $('#nutrition-water'),
    nutritionType: $('#nutrition-type'),
    nutritionDate: $('#nutrition-date'),
    nutritionName: $('#nutrition-name'),
    nutritionCaloriesInput: $('#nutrition-calories-input'),
    nutritionProteinInput: $('#nutrition-protein-input'),
    nutritionWaterInput: $('#nutrition-water-input'),
    nutritionNote: $('#nutrition-note'),
    btnAddNutrition: $('#btn-add-nutrition'),
    nutritionStatus: $('#nutrition-status'),
    nutritionList: $('#nutrition-list'),

    recoveryLatestSleep: $('#recovery-latest-sleep'),
    recoveryLatestDate: $('#recovery-latest-date'),
    recoveryWeekSleep: $('#recovery-week-sleep'),
    recoveryWeekCount: $('#recovery-week-count'),
    recoveryTodayState: $('#recovery-today-state'),
    recoveryDate: $('#recovery-date'),
    recoverySleepHours: $('#recovery-sleep-hours'),
    recoverySleepQuality: $('#recovery-sleep-quality'),
    recoveryEnergy: $('#recovery-energy'),
    recoveryMood: $('#recovery-mood'),
    recoveryNote: $('#recovery-note'),
    btnSaveRecovery: $('#btn-save-recovery'),
    recoveryStatus: $('#recovery-status'),
    recoveryList: $('#recovery-list'),

    studyTodayMinutes: $('#study-today-minutes'),
    studyTodayCount: $('#study-today-count'),
    studyWeekMinutes: $('#study-week-minutes'),
    studyWeekCount: $('#study-week-count'),
    studyWeekFocus: $('#study-week-focus'),
    studySubject: $('#study-subject'),
    studyDate: $('#study-date'),
    studyDuration: $('#study-duration'),
    studyFocus: $('#study-focus'),
    studyFocusOutput: $('#study-focus-output'),
    studyNote: $('#study-note'),
    btnAddStudy: $('#btn-add-study'),
    studyStatus: $('#study-status'),
    studyList: $('#study-list'),

    rhythmTaskProgress: $('#rhythm-task-progress'),
    rhythmTaskNote: $('#rhythm-task-note'),
    rhythmOverdue: $('#rhythm-overdue'),
    rhythmHabitProgress: $('#rhythm-habit-progress'),
    rhythmHabitNote: $('#rhythm-habit-note'),
    taskTitle: $('#task-title'),
    taskDue: $('#task-due'),
    taskPriority: $('#task-priority'),
    taskCategory: $('#task-category'),
    btnAddTask: $('#btn-add-task'),
    taskStatus: $('#task-status'),
    taskList: $('#task-list'),
    habitName: $('#habit-name'),
    habitCategory: $('#habit-category'),
    btnAddHabit: $('#btn-add-habit'),
    habitStatus: $('#habit-status'),
    habitList: $('#habit-list'),

    reflectionDate: $('#reflection-date'),
    reflectionHighlight: $('#reflection-highlight'),
    reflectionChallenge: $('#reflection-challenge'),
    reflectionGratitude: $('#reflection-gratitude'),
    reflectionNote: $('#reflection-note'),
    btnSaveReflection: $('#btn-save-reflection'),
    reflectionStatus: $('#reflection-status'),
    reflectionWeekExpense: $('#reflection-week-expense'),
    reflectionWeekFitness: $('#reflection-week-fitness'),
    reflectionWeekFitnessNote: $('#reflection-week-fitness-note'),
    reflectionWeekStudy: $('#reflection-week-study'),
    reflectionWeekStudyNote: $('#reflection-week-study-note'),
    reflectionWeekSleep: $('#reflection-week-sleep'),
    reflectionWeekSleepNote: $('#reflection-week-sleep-note'),
    reflectionWeekRange: $('#reflection-week-range'),
    reflectionWeekFinanceDetail: $('#reflection-week-finance-detail'),
    reflectionWeekNutritionDetail: $('#reflection-week-nutrition-detail'),
    reflectionWeekRecoveryDetail: $('#reflection-week-recovery-detail'),
    reflectionWeekRhythmDetail: $('#reflection-week-rhythm-detail'),
    reflectionWeekReflectionCount: $('#reflection-week-reflection-count'),
    reflectionList: $('#reflection-list'),

    lifeCalendarActiveDays: $('#life-calendar-active-days'),
    lifeCalendarFactCount: $('#life-calendar-fact-count'),
    lifeCalendarArrangementCount: $('#life-calendar-arrangement-count'),
    lifeCalendarMonthLabel: $('#life-calendar-month-label'),
    lifeCalendarGrid: $('#life-calendar-grid'),
    lifeCalendarSelectedDate: $('#life-calendar-selected-date'),
    lifeCalendarDaySummary: $('#life-calendar-day-summary'),
    lifeCalendarFacts: $('#life-calendar-facts'),
    lifeCalendarArrangements: $('#life-calendar-arrangements'),
    lifeCalendarStatus: $('#life-calendar-status'),
    lifeCalendarPrev: $('#life-calendar-prev'),
    lifeCalendarToday: $('#life-calendar-today'),
    lifeCalendarNext: $('#life-calendar-next'),

    goalsActiveCount: $('#goals-active-count'),
    goalsCompletedCount: $('#goals-completed-count'),
    goalsMilestoneProgress: $('#goals-milestone-progress'),
    goalTitle: $('#goal-title'),
    goalCategory: $('#goal-category'),
    goalTargetDate: $('#goal-target-date'),
    goalMotivation: $('#goal-motivation'),
    btnAddLifeGoal: $('#btn-add-life-goal'),
    goalsStatus: $('#goals-status'),
    goalsList: $('#goals-list'),

    btnLifeSearch: $('#btn-life-search'),
    lifeSearchOverlay: $('#life-search-overlay'),
    btnCloseLifeSearch: $('#btn-close-life-search'),
    lifeSearchInput: $('#life-search-input'),
    lifeSearchModule: $('#life-search-module'),
    lifeSearchDateFrom: $('#life-search-date-from'),
    lifeSearchDateTo: $('#life-search-date-to'),
    btnRunLifeSearch: $('#btn-run-life-search'),
    btnResetLifeSearch: $('#btn-reset-life-search'),
    lifeSearchSummary: $('#life-search-summary'),
    lifeSearchResults: $('#life-search-results'),
    lifeSearchStatus: $('#life-search-status'),

    overlay: $('#overlay'),
    btnSettings: $('#btn-settings'),
    cfgBirth: $('#cfg-birth'),
    cfgTargetAge: $('#cfg-target-age'),
    cfgShowPast: $('#cfg-show-past'),
    cfgTrackingDays: $('#cfg-tracking-days'),
    cfgAvgExpense: $('#cfg-avg-expense'),
    cfgSave: $('#cfg-save'),
    cfgCancel: $('#cfg-cancel'),
    modalTargetAgeDisplay: $('#modal-target-age-display'),

    ringPct: $('#ring-pct'),
    litCount: $('#lit-count'),
    remainingDays: $('#remaining-days'),
    barAsset: $('#bar-asset'),
    barIncome: $('#bar-income'),
    rowAsset: $('#row-asset'),
    assetDays: $('#asset-days'),
    assetAmount: $('#asset-amount'),
    incomeDays: $('#income-days'),
    netSaving: $('#net-saving'),
    autonomyRate: $('#autonomy-rate'),
    autonomyDays: $('#autonomy-days'),

    segBtns: document.querySelectorAll('.seg__btn'),
    txAmount: $('#tx-amount'),
    txDate: $('#tx-date'),
    txNote: $('#tx-note'),
    txSource: $('#tx-source'),
    incomeSourceField: $('#income-source-field'),
    txAccount: $('#tx-account'),
    txCategory: $('#tx-category'),
    expenseCategoryField: $('#expense-category-field'),
    btnSubmit: $('#btn-submit'),

    stFamily: $('#st-family'),
    stIndependent: $('#st-independent'),
    stExpense: $('#st-expense'),
    stAvg: $('#st-avg'),

    txList: $('.tx-list'),
    txItems: $('#tx-items'),
    txCount: $('#tx-count'),

    legendOverflow: $('#legend-overflow'),
    stageFooter: $('#stage-footer-text'),
    stageChrome: $('#stage-chrome'),
    stageTitleCn: $('#stage-title-cn'),
    stageTitleEn: $('#stage-title-en'),
    stageLegend: $('#stage-legend'),
    viewTabs: document.querySelectorAll('.view-tab'),
    stageViews: document.querySelectorAll('[data-stage-view]'),
    freedomBanner: $('#freedom-banner'),

    todayHero: $('#today-hero'),
    todayHeadline: $('#today-headline'),
    todayDate: $('#today-date'),
    todayAvailable: $('#today-available'),
    todayBudgetBasis: $('#today-budget-basis'),
    todaySpent: $('#today-spent'),
    todayMonthRemaining: $('#today-month-remaining'),
    todayMonthStatus: $('#today-month-status'),
    todayNextAllowance: $('#today-next-allowance'),
    todayNextBalance: $('#today-next-balance'),
    todayReminders: $('#today-reminders'),
    focusTime: $('#focus-time'),
    focusMeta: $('#focus-meta'),
    focusIdle: $('#focus-idle'),
    focusRunning: $('#focus-running'),
    focusSubject: $('#focus-subject'),
    focusMinutes: $('#focus-minutes'),
    focusRating: $('#focus-rating'),
    focusRatingOutput: $('#focus-rating-output'),
    focusStatus: $('#focus-status'),
    focusToday: $('#focus-today'),
    btnFocusStart: $('#btn-focus-start'),
    btnBreakShort: $('#btn-break-short'),
    btnBreakLong: $('#btn-break-long'),
    btnFocusFinish: $('#btn-focus-finish'),
    btnFocusDrop: $('#btn-focus-drop'),
    bodyWeight: $('#body-weight'),
    bodyWeightDelta: $('#body-weight-delta'),
    bodyWaist: $('#body-waist'),
    bodyWaistDelta: $('#body-waist-delta'),
    bodyDays: $('#body-days'),
    bodyCount: $('#body-count'),
    bodyDate: $('#body-date'),
    bodyWeightInput: $('#body-weight-input'),
    bodyFatInput: $('#body-fat-input'),
    bodyWaistInput: $('#body-waist-input'),
    bodyChestInput: $('#body-chest-input'),
    bodyArmInput: $('#body-arm-input'),
    bodyNoteInput: $('#body-note-input'),
    btnSaveBody: $('#btn-save-body'),
    bodyStatus: $('#body-status'),
    bodyList: $('#body-list'),
    healthFile: $('#health-file'),
    healthKind: $('#health-kind'),
    btnAnalyzeHealth: $('#btn-analyze-health'),
    healthSummary: $('#health-summary'),
    healthPreview: $('#health-preview'),
    btnCommitHealth: $('#btn-commit-health'),
    healthError: $('#health-error'),
    setSession: $('#set-session'),
    setExercise: $('#set-exercise'),
    setReps: $('#set-reps'),
    setWeight: $('#set-weight'),
    setDistance: $('#set-distance'),
    setDuration: $('#set-duration'),
    btnAddSet: $('#btn-add-set'),
    setStatus: $('#set-status'),
    exerciseName: $('#exercise-name'),
    exerciseKind: $('#exercise-kind'),
    btnAddExercise: $('#btn-add-exercise'),
    trainingList: $('#training-list'),
    trainingWeekVolume: $('#training-week-volume'),
    recordsList: $('#records-list'),
    inboxOpen: $('#inbox-open'),
    inboxFiled: $('#inbox-filed'),
    inboxOldest: $('#inbox-oldest'),
    inboxInput: $('#inbox-input'),
    btnAddInbox: $('#btn-add-inbox'),
    inboxStatus: $('#inbox-status'),
    inboxList: $('#inbox-list'),
    insightsDays: $('#insights-days'),
    insightsNote: $('#insights-note'),
    insightsList: $('#insights-list'),
    healthMetricList: $('#health-list'),
    tagsList: $('#tags-list'),
    btnCleanupTags: $('#btn-cleanup-tags'),
    captureList: $('#capture-list'),
    captureCount: $('#capture-count'),
    captureHealth: $('#capture-health'),
    todayGoals: $('#today-goals'),
    todaySemester: $('#today-semester'),
    quickEntryInput: $('#quick-entry-input'),
    btnQuickParse: $('#btn-quick-parse'),
    quickEntryStatus: $('#quick-entry-status'),
    quickPreview: $('#quick-preview'),
    quickConfidence: $('#quick-confidence'),
    quickType: $('#quick-type'),
    quickAmount: $('#quick-amount'),
    quickAccount: $('#quick-account'),
    quickCategory: $('#quick-category'),
    quickCategoryField: $('#quick-category-field'),
    quickSource: $('#quick-source'),
    quickSourceField: $('#quick-source-field'),
    quickDate: $('#quick-date'),
    quickNote: $('#quick-note'),
    quickWarnings: $('#quick-warnings'),
    quickModules: $('#quick-modules'),
    quickFinanceFields: $('#quick-finance-fields'),
    quickDynamic: $('#quick-dynamic'),
    btnQuickConfirm: $('#btn-quick-confirm'),
    btnQuickCancel: $('#btn-quick-cancel'),

    dashTotalBalance: $('#dash-total-balance'),
    dashAccountCount: $('#dash-account-count'),
    dashFamily: $('#dash-family'),
    dashIndependent: $('#dash-independent'),
    dashAutonomy: $('#dash-autonomy'),
    dashExpense: $('#dash-expense'),
    dashNet: $('#dash-net'),
    dashMonthLabel: $('#dash-month-label'),
    accountList: $('#account-list'),
    accountName: $('#account-name'),
    accountType: $('#account-type'),
    accountOpening: $('#account-opening'),
    btnAddAccount: $('#btn-add-account'),
    accountError: $('#account-error'),
    categoryBars: $('#category-bars'),
    trendChart: $('#trend-chart'),
    transferFrom: $('#transfer-from'),
    transferTo: $('#transfer-to'),
    transferAmount: $('#transfer-amount'),
    transferDate: $('#transfer-date'),
    transferNote: $('#transfer-note'),
    btnTransfer: $('#btn-transfer'),
    transferError: $('#transfer-error'),
    reconcileAccount: $('#reconcile-account'),
    reconcileBalance: $('#reconcile-balance'),
    reconcileNote: $('#reconcile-note'),
    btnReconcile: $('#btn-reconcile'),
    reconcileError: $('#reconcile-error'),
    transferList: $('#transfer-list'),

    planMonthEnd: $('#plan-month-end'),
    planMonthEndNote: $('#plan-month-end-note'),
    planNextDate: $('#plan-next-date'),
    planNextBalance: $('#plan-next-balance'),
    planGoalAllocated: $('#plan-goal-allocated'),
    planUnallocated: $('#plan-unallocated'),
    planDailyRate: $('#plan-daily-rate'),
    planSpendingBasis: $('#plan-spending-basis'),
    planAllowanceAmount: $('#plan-allowance-amount'),
    planAllowanceDay: $('#plan-allowance-day'),
    planBudget: $('#plan-budget'),
    btnSavePlan: $('#btn-save-plan'),
    planSettingsStatus: $('#plan-settings-status'),
    semesterStart: $('#semester-start'),
    semesterEnd: $('#semester-end'),
    semesterBudget: $('#semester-budget'),
    semesterMode: $('#semester-mode'),
    btnSaveSemester: $('#btn-save-semester'),
    semesterStatus: $('#semester-status'),
    semesterBadge: $('#semester-badge'),
    semesterActual: $('#semester-actual'),
    semesterRemaining: $('#semester-remaining'),
    semesterDaily: $('#semester-daily'),
    semesterProgress: $('#semester-progress'),
    semesterCopy: $('#semester-copy'),
    goalName: $('#goal-name'),
    goalTarget: $('#goal-target'),
    goalSaved: $('#goal-saved'),
    goalDate: $('#goal-date'),
    btnAddGoal: $('#btn-add-goal'),
    goalError: $('#goal-error'),
    goalList: $('#goal-list'),
    budgetOverall: $('#budget-overall'),
    budgetList: $('#budget-list'),
    btnSaveBudgets: $('#btn-save-budgets'),
    budgetStatus: $('#budget-status'),
    importFile: $('#import-file'),
    importAccount: $('#import-account'),
    btnAnalyzeImport: $('#btn-analyze-import'),
    btnDownloadTemplate: $('#btn-download-template'),
    importSummary: $('#import-summary'),
    importPreview: $('#import-preview'),
    btnCommitImport: $('#btn-commit-import'),
    statementFile: $('#statement-file'),
    statementSource: $('#statement-source'),
    btnAnalyzeStatement: $('#btn-analyze-statement'),
    statementSummary: $('#statement-summary'),
    statementPreview: $('#statement-preview'),
    btnCommitStatement: $('#btn-commit-statement'),
    statementError: $('#statement-error'),
    importError: $('#import-error'),
    importHistory: $('#import-history'),

    reviewNet: $('#review-net'),
    reviewTxCount: $('#review-tx-count'),
    reviewExpense: $('#review-expense'),
    reviewExpenseChange: $('#review-expense-change'),
    reviewBills: $('#review-bills'),
    reviewBillCount: $('#review-bill-count'),
    reviewAlerts: $('#review-alerts'),
    billCalendarMonth: $('#bill-calendar-month'),
    billCalendarGrid: $('#bill-calendar-grid'),
    billName: $('#bill-name'),
    billAmount: $('#bill-amount'),
    billDay: $('#bill-day'),
    billCategory: $('#bill-category'),
    billAccount: $('#bill-account'),
    billNote: $('#bill-note'),
    btnAddBill: $('#btn-add-bill'),
    billError: $('#bill-error'),
    billList: $('#bill-list'),
    reviewTopCategory: $('#review-top-category'),
    reviewSavingRate: $('#review-saving-rate'),
    reviewScheduled: $('#review-scheduled'),
    reviewObservations: $('#review-observations'),

    annualIncome: $('#annual-income'),
    annualActiveMonths: $('#annual-active-months'),
    annualExpense: $('#annual-expense'),
    annualTxCount: $('#annual-tx-count'),
    annualNet: $('#annual-net'),
    annualSavingRate: $('#annual-saving-rate'),
    searchCount: $('#search-count'),
    searchNet: $('#search-net'),
    annualYear: $('#annual-year'),
    btnLoadAnnual: $('#btn-load-annual'),
    btnExportAnnual: $('#btn-export-annual'),
    annualChart: $('#annual-chart'),
    annualBestMonth: $('#annual-best-month'),
    annualHighestExpense: $('#annual-highest-expense'),
    annualIncomeMix: $('#annual-income-mix'),
    annualCategories: $('#annual-categories'),
    btnExportBackup: $('#btn-export-backup'),
    restoreFile: $('#restore-file'),
    restorePreview: $('#restore-preview'),
    restoreConfirm: $('#restore-confirm'),
    btnRestoreBackup: $('#btn-restore-backup'),
    backupStatus: $('#backup-status'),
    searchQuery: $('#search-query'),
    searchType: $('#search-type'),
    searchCategory: $('#search-category'),
    searchAccount: $('#search-account'),
    searchDateFrom: $('#search-date-from'),
    searchDateTo: $('#search-date-to'),
    btnSearch: $('#btn-search'),
    btnResetSearch: $('#btn-reset-search'),
    searchSummary: $('#search-summary'),
    searchResults: $('#search-results'),

    canvas: $('#grid'),
    starfield: $('#starfield'),
  };

  els.planAllowanceDay.innerHTML = Array.from({ length: 28 }, (_, index) => {
    const day = index + 1;
    return `<option value="${day}">每月 ${day} 日</option>`;
  }).join('');
  els.billDay.innerHTML = Array.from({ length: 28 }, (_, index) => {
    const day = index + 1;
    return `<option value="${day}">每月 ${day} 日</option>`;
  }).join('');
  els.annualYear.value = String(new Date().getFullYear());

  // ---------- 引擎 ----------
  const audio = new window.RitualAudio();
  const grid = new window.LifeGrid(els.canvas, audio);
  const stars = new window.Starfield(els.starfield);

  // 首次点击任意按钮即解锁 AudioContext（autoplay policy）
  const primeAudio = () => audio.ensure();
  document.addEventListener('pointerdown', primeAudio, { once: true });

  // ============================================
  // DatePicker · cinematic dark calendar
  //   - 包装 input[type=hidden] · 暴露 .value / change 事件
  //   - 每个 .date-input[data-picker] 实例化一次
  // ============================================
  class DatePicker {
    constructor(root) {
      this.root = root;
      this.hidden = root.querySelector('input[type=hidden]');
      this.trigger = root.querySelector('.date-input__trigger');
      this.valueEl = root.querySelector('.date-input__value');
      this.popover = root.querySelector('.date-popover');
      this.titleEl = root.querySelector('.date-popover__title');
      this.gridEl  = root.querySelector('.date-popover__grid');
      this.viewYear = new Date().getFullYear();
      this.viewMonth = new Date().getMonth();
      this._bind();
      this._sync();
    }
    get value() { return this.hidden.value || ''; }
    setValue(iso) {
      this.hidden.value = iso || '';
      if (iso) {
        const d = this._parse(iso);
        this.viewYear = d.getFullYear();
        this.viewMonth = d.getMonth();
      }
      this._sync();
      this.root.dispatchEvent(new CustomEvent('change', { detail: this.value }));
    }
    open() {
      const v = this.value;
      if (v) {
        const d = this._parse(v);
        this.viewYear = d.getFullYear();
        this.viewMonth = d.getMonth();
      }
      this._render();
      this.popover.hidden = false;
      this.root.classList.add('is-open');
      setTimeout(() => document.addEventListener('pointerdown', this._outside, true), 0);
      document.addEventListener('keydown', this._onEsc);
    }
    close() {
      this.popover.hidden = true;
      this.root.classList.remove('is-open');
      document.removeEventListener('pointerdown', this._outside, true);
      document.removeEventListener('keydown', this._onEsc);
    }
    _bind() {
      this.trigger.addEventListener('click', () => this.popover.hidden ? this.open() : this.close());
      this.popover.addEventListener('click', (e) => {
        const nav = e.target.closest('[data-nav]');
        const action = e.target.closest('[data-action]');
        const day = e.target.closest('[data-day]');
        if (nav) {
          const dir = nav.dataset.nav;
          if (dir === 'prev')      { if (--this.viewMonth < 0) { this.viewMonth = 11; this.viewYear--; } }
          else if (dir === 'next') { if (++this.viewMonth > 11) { this.viewMonth = 0; this.viewYear++; } }
          else if (dir === 'prev-year') this.viewYear--;
          else if (dir === 'next-year') this.viewYear++;
          this._render();
        } else if (action === null && day) {
          if (!day.classList.contains('is-disabled')) {
            this.setValue(day.dataset.day);
            this.close();
          }
        } else if (action) {
          if (action.dataset.action === 'today')  { this.setValue(this._iso(new Date())); this.close(); }
          else if (action.dataset.action === 'clear') { this.setValue(''); this.close(); }
        }
      });
      this._outside = (e) => { if (!this.root.contains(e.target)) this.close(); };
      this._onEsc = (e) => { if (e.key === 'Escape') this.close(); };
    }
    _sync() {
      const v = this.value;
      if (v) {
        const d = this._parse(v);
        this.valueEl.textContent = `${d.getFullYear()} 年 ${d.getMonth()+1} 月 ${d.getDate()} 日`;
        this.root.classList.remove('is-empty');
      } else {
        this.valueEl.textContent = this.valueEl.dataset.placeholder || '选择日期';
        this.root.classList.add('is-empty');
      }
    }
    _render() {
      this.titleEl.textContent = `${this.viewYear} 年 ${this.viewMonth + 1} 月`;
      const y = this.viewYear, m = this.viewMonth;
      const todayISO = this._iso(new Date());
      const valueISO = this.value;
      const first = new Date(y, m, 1);
      const daysIn = new Date(y, m + 1, 0).getDate();
      const prevLast = new Date(y, m, 0).getDate();
      const startDow = first.getDay();
      const cells = [];
      for (let i = startDow - 1; i >= 0; i--) {
        const d = new Date(y, m - 1, prevLast - i);
        cells.push({ d, day: prevLast - i, other: true });
      }
      for (let day = 1; day <= daysIn; day++) {
        cells.push({ d: new Date(y, m, day), day, other: false });
      }
      while (cells.length < 42) {
        const k = cells.length - startDow - daysIn + 1;
        cells.push({ d: new Date(y, m + 1, k), day: k, other: true });
      }
      this.gridEl.innerHTML = cells.map(c => {
        const iso = this._iso(c.d);
        const cls = ['date-day'];
        if (c.other) cls.push('is-other');
        if (iso === todayISO) cls.push('is-today');
        if (iso === valueISO) cls.push('is-selected');
        return `<button type="button" class="${cls.join(' ')}" data-day="${iso}">${c.day}</button>`;
      }).join('');
    }
    _iso(d) {
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${d.getFullYear()}-${m}-${day}`;
    }
    _parse(iso) {
      // 避免时区误差，按本地零点解析
      const [y, m, d] = iso.split('-').map(Number);
      return new Date(y, m - 1, d);
    }
  }

  // 实例化所有 date-input
  const datePickers = new Map();
  document.querySelectorAll('.date-input[data-picker]').forEach(root => {
    const id = root.querySelector('input[type=hidden]').id;
    datePickers.set(id, new DatePicker(root));
  });
  const txDP = datePickers.get('tx-date');
  const birthDP = datePickers.get('cfg-birth');

  // ============================================
  // 渲染
  // ============================================
  function renderProgress() {
    const s = state.stats;
    const future = s.future_cells || s.total_cells || 1;
    const lit = s.lit_count || 0;
    // 百分比 = 已点亮 / 从今天到终结日 · 与 show_past 无关
    const ratio = Math.min(lit / future, 1);

    // 标题百分比
    els.ringPct.textContent = (ratio * 100).toFixed(1);

    // 大数字 + 副标
    els.litCount.textContent = fmtInt(lit);
    els.remainingDays.textContent = fmtInt(Math.max(0, future - lit));

    // 双段进度条（按未来格 future_cells 算比例，避免 show_past 模式下被 past 段稀释）
    const denom = (s.future_cells || s.total_cells) || 1;
    const assetPct = Math.min(100, (s.asset_lit / denom) * 100);
    const incomePct = Math.min(100 - assetPct, (s.income_lit / denom) * 100);
    els.barAsset.style.width = assetPct.toFixed(2) + '%';
    els.barIncome.style.width = incomePct.toFixed(2) + '%';

    // 分项
    const showAsset = (s.support_balance || 0) > 0;
    els.rowAsset.hidden = !showAsset;
    els.assetDays.textContent = fmtInt(s.asset_lit || 0);
    els.assetAmount.textContent = fmtCNY(s.support_balance || 0);
    els.incomeDays.textContent = fmtInt(s.income_lit || 0);
    els.netSaving.textContent = fmtCNY(s.independent_balance || 0);

    const autonomyRate = s.autonomy_coverage_rate;
    els.autonomyRate.textContent = autonomyRate == null ? '—' : `${Number(autonomyRate).toFixed(1)}%`;
    els.autonomyDays.textContent = `${fmtInt(s.independent_coverage_days || 0)} 天自主覆盖`;

    els.legendOverflow.hidden = !s.overflow;
  }

  function renderStats() {
    const s = state.stats;
    els.stFamily.textContent = fmtCNY(s.family_support_income);
    els.stIndependent.textContent = fmtCNY(s.independent_income);
    els.stExpense.textContent = fmtCNY(s.total_expense);
    els.stAvg.textContent = fmtCNY(s.avg_daily_expense);

    if (state.currentView === 'today') {
      const today = state.today || {};
      els.stageFooter.textContent = `${today.date || todayISO()} · 今日真实支出 ${fmtCNY(today.today_expense)} · 快速记账只在确认后写入真实账本`;
    } else if (state.currentView === 'data') {
      const summary = state.annualReport?.summary || {};
      els.stageFooter.textContent = `${state.annualReport?.year || '年度'} · ${fmtInt(summary.transaction_count)} 笔交易 · 净现金流 ${fmtSignedCNY(summary.net_cashflow)} · 数据仅保存在本机`;
    } else if (state.currentView === 'review') {
      const summary = state.calendar?.summary || {};
      els.stageFooter.textContent = `${state.calendar?.month || '本月'} · 固定账单 ${fmtCNY(summary.scheduled_amount)} · 待支付 ${fmtCNY(summary.unpaid_amount)} · 复盘只使用真实记录`;
    } else if (state.currentView === 'planning') {
      const forecast = state.planning?.forecast || {};
      els.stageFooter.textContent = `规划不会改变真实账本 · 预计月底 ${fmtCNY(forecast.projected_month_end_balance)} · ${state.planning?.goals?.length || 0} 个储蓄目标`;
    } else if (state.currentView === 'dashboard') {
      const monthly = state.monthly || {};
      els.stageFooter.textContent = `${monthly.month || '本月'} · ${state.accounts.length} 个账户 · 总余额 ${fmtCNY(s.current_balance)}`;
    } else if (s.tracking_days > 0) {
      els.stageFooter.textContent =
        `已记账 ${s.tracking_days} 天 · 日均 ${fmtCNY(s.avg_daily_expense)} · 当前资金续航 ${fmtInt(s.runway_days)} 天 · 自主收入覆盖 ${fmtInt(s.independent_coverage_days)} 天`;
    } else {
      els.stageFooter.textContent = '先记录一笔支出，系统才能估算你的真实生活成本';
    }
  }

  function fillAccountSelect(select, selectedId = null) {
    const selected = Number(selectedId || select.value || 0);
    select.innerHTML = '';
    for (const account of state.accounts) {
      const option = document.createElement('option');
      option.value = String(account.id);
      option.textContent = account.name;
      select.appendChild(option);
    }
    if (state.accounts.some(account => account.id === selected)) {
      select.value = String(selected);
    }
  }

  function fillSearchAccountSelect() {
    const selected = els.searchAccount.value;
    els.searchAccount.innerHTML = '<option value="">全部账户</option>' + state.accounts
      .map(account => `<option value="${account.id}">${escapeHtml(account.name)}</option>`)
      .join('');
    if ([...els.searchAccount.options].some(option => option.value === selected)) {
      els.searchAccount.value = selected;
    }
  }

  function renderAccountSelect() {
    const previousFrom = Number(els.transferFrom.value || 0);
    const previousTo = Number(els.transferTo.value || 0);
    fillAccountSelect(els.txAccount);
    fillAccountSelect(els.transferFrom, previousFrom);
    fillAccountSelect(els.transferTo, previousTo);
    fillAccountSelect(els.reconcileAccount);
    fillAccountSelect(els.importAccount);
    fillAccountSelect(els.billAccount);
    fillAccountSelect(els.quickAccount, state.quickPreview?.transaction?.account_id);
    fillSearchAccountSelect();
    if (state.accounts.length > 1 && els.transferFrom.value === els.transferTo.value) {
      const alternative = state.accounts.find(account => String(account.id) !== els.transferFrom.value);
      if (alternative) els.transferTo.value = String(alternative.id);
    }
    els.btnSubmit.disabled = state.accounts.length === 0;
    els.btnTransfer.disabled = state.accounts.length < 2;
    els.btnReconcile.disabled = state.accounts.length === 0;
    const reconcile = state.accounts.find(account => String(account.id) === els.reconcileAccount.value);
    els.reconcileBalance.placeholder = reconcile
      ? `当前 ${fmtCNY(reconcile.balance)}`
      : '输入现在看到的余额';
  }

  function renderAccounts() {
    els.accountList.innerHTML = '';
    if (!state.accounts.length) {
      els.accountList.innerHTML = '<div class="dashboard-empty">还没有账户，请先创建一个。</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    for (const account of state.accounts) {
      const card = document.createElement('article');
      card.className = `account-card account-card--${account.type}`;
      card.innerHTML = `
        <span class="account-card__mark"></span>
        <div><strong>${escapeHtml(account.name)}</strong><small>${ACCOUNT_TYPE_LABELS[account.type] || '其他'} · ${fmtInt(account.activity_count)} 条账户记录</small></div>
        <em>${fmtCNY(account.balance)}</em>
      `;
      frag.appendChild(card);
    }
    els.accountList.appendChild(frag);
  }

  function renderCategoryBars() {
    const categories = state.monthly?.expense_categories || {};
    const rows = Object.entries(categories)
      .filter(([, value]) => Number(value) > 0)
      .sort((a, b) => b[1] - a[1]);
    if (!rows.length) {
      els.categoryBars.innerHTML = '<div class="dashboard-empty">本月还没有支出分类数据。</div>';
      return;
    }
    const max = Math.max(...rows.map(([, value]) => Number(value)), 1);
    els.categoryBars.innerHTML = rows.map(([key, value]) => `
      <div class="category-row">
        <span>${CATEGORY_LABELS[key] || '其他'}</span>
        <div><i style="width:${(Number(value) / max * 100).toFixed(1)}%"></i></div>
        <em>${fmtCNY(value)}</em>
      </div>
    `).join('');
  }

  function renderTrend() {
    const trend = state.monthly?.trend || [];
    const max = Math.max(...trend.flatMap(row => [Number(row.expense), Number(row.independent)]), 1);
    els.trendChart.innerHTML = trend.map(row => {
      const independentHeight = Number(row.independent) > 0 ? Math.max(3, Number(row.independent) / max * 100) : 0;
      const expenseHeight = Number(row.expense) > 0 ? Math.max(3, Number(row.expense) / max * 100) : 0;
      return `
        <div class="trend-month" title="${row.month} · 自主 ${fmtCNY(row.independent)} · 支出 ${fmtCNY(row.expense)}">
          <div class="trend-month__bars">
            <i class="trend-month__independent" style="height:${independentHeight.toFixed(1)}%"></i>
            <i class="trend-month__expense" style="height:${expenseHeight.toFixed(1)}%"></i>
          </div>
          <span>${row.month.slice(5)}月</span>
        </div>
      `;
    }).join('');
  }

  function renderTransfers() {
    if (!state.transfers.length) {
      els.transferList.innerHTML = '<div class="dashboard-empty">还没有账户间转账。</div>';
      return;
    }
    els.transferList.innerHTML = state.transfers.map(transfer => `
      <div class="transfer-item">
        <div>
          <strong>${escapeHtml(transfer.from_account_name)} <span>→</span> ${escapeHtml(transfer.to_account_name)}</strong>
          <small>${transfer.occurred_on}${transfer.note ? ` · ${escapeHtml(transfer.note)}` : ''}</small>
        </div>
        <em>${fmtCNY(transfer.amount)}</em>
        <button data-transfer-delete="${transfer.id}" title="撤销这笔转账" aria-label="撤销转账">×</button>
      </div>
    `).join('');
    els.transferList.querySelectorAll('[data-transfer-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteTransfer(Number(button.dataset.transferDelete)));
    });
  }

  const CAPTURE_CATEGORIES = [
    ['food', '餐饮'], ['transport', '交通'], ['study', '学习'], ['housing', '居住'],
    ['medical', '医疗'], ['entertainment', '娱乐'], ['social', '社交'],
    ['digital', '数字服务'], ['other', '其他'],
  ];

  // ---------- 待确认捕获 ----------
  // 这里显示的都还不是交易：确认之前它们不进入余额、月度和预算的任何一项。
  function renderCapture() {
    const capture = state.capture || {};
    const pending = capture.pending || [];
    const summary = capture.summary || {};

    els.captureCount.hidden = !pending.length;
    els.captureCount.textContent = pending.length ? `${pending.length} 条待确认` : '';

    if (!pending.length) {
      els.captureList.innerHTML =
        '<div class="today-empty">没有待确认的捕获。<br>这只说明捕获通道当前没有抓到事件，不代表没有消费。</div>';
    } else {
      els.captureList.innerHTML = pending.map(item => `
        <div class="capture-item" data-capture="${item.id}">
          <div class="capture-item__main">
            <strong>${fmtCNY(item.amount)}</strong>
            <span>${escapeHtml(item.merchant || item.raw_text)}</span>
            <small>${escapeHtml((item.channel_labels || []).join(' + '))} · ${escapeHtml(item.occurred_on)}${
              item.suggested ? ` · 按「${escapeHtml(item.suggested.keyword)}」预选` : ''}</small>
          </div>
          <div class="capture-item__actions">
            <select data-capture-category="${item.id}" aria-label="支出分类">
              ${CAPTURE_CATEGORIES.map(([key, label]) =>
                `<option value="${key}"${key === (item.suggested?.category || 'other') ? ' selected' : ''}>${label}</option>`
              ).join('')}
            </select>
            <button data-capture-confirm="${item.id}">确认记账</button>
            <button class="ghost" data-capture-dismiss="${item.id}">忽略</button>
          </div>
        </div>`).join('');

      els.captureList.querySelectorAll('[data-capture-confirm]').forEach(button => {
        button.addEventListener('click', () => onConfirmCapture(Number(button.dataset.captureConfirm)));
      });
      els.captureList.querySelectorAll('[data-capture-dismiss]').forEach(button => {
        button.addEventListener('click', () => onDismissCapture(Number(button.dataset.captureDismiss)));
      });
    }

    // 通道健康度：静默失败是通知监听最大的坑，必须在界面上看得见。
    if (!summary.last_capture_at) {
      els.captureHealth.textContent = '还没有收到过任何捕获事件。手机端配置好之后这里会开始有数据。';
    } else {
      const days = Math.floor((Date.now() - new Date(summary.last_capture_at).getTime()) / 86400000);
      const label = capture.channel_labels?.[summary.last_capture_channel] || summary.last_capture_channel;
      els.captureHealth.textContent = days >= 3
        ? `最近一次捕获是 ${days} 天前（${label}）。间隔这么久，建议检查手机上的监听是不是被系统关掉了。`
        : `最近一次捕获：${label} · ${days === 0 ? '今天' : `${days} 天前`}`;
    }
  }

  async function onConfirmCapture(id) {
    if (state.busy) return;
    const select = els.captureList.querySelector(`[data-capture-category="${id}"]`);
    state.busy = true;
    try {
      const response = await api.confirmCapture(id, { category: select ? select.value : 'other' });
      state.capture = response.capture_state;
      state.stats = response.stats;
      state.today = response.today;
      renderCapture();
      renderStats();
      renderToday();
      renderProgress();
    } finally { state.busy = false; }
  }

  async function onDismissCapture(id) {
    if (state.busy || !window.confirm('忽略这条捕获？它不会变成交易，但这笔钱可能确实花了。')) return;
    state.busy = true;
    try {
      const response = await api.dismissCapture(id);
      state.capture = response.capture_state;
      renderCapture();
    } finally { state.busy = false; }
  }

  // ---------- 身体指标 ----------
  // 留空的指标是「没量」，不是 0；变化量只描述差值，不解释原因。
  function renderBody() {
    const state_ = state.body || {};
    const changes = state_.changes || {};
    const describe = (key, unit) => {
      const change = changes[key];
      if (!change) return { value: '—', hint: '还没有记录' };
      const delta = change.delta;
      const hint = delta == null
        ? `第一次记录 · ${change.measured_on}`
        : `${delta > 0 ? '+' : ''}${delta}${unit} · 距上次 ${change.days_between} 天`;
      return { value: `${change.value}${unit}`, hint };
    };
    const weight = describe('weight_kg', 'kg');
    const waist = describe('waist_cm', 'cm');
    els.bodyWeight.textContent = weight.value;
    els.bodyWeightDelta.textContent = weight.hint;
    els.bodyWaist.textContent = waist.value;
    els.bodyWaistDelta.textContent = waist.hint;
    els.bodyDays.textContent = state_.days_since_last == null ? '—' : `${state_.days_since_last} 天`;
    els.bodyCount.textContent = `共 ${fmtInt(state_.measured_count || 0)} 条记录`;

    const rows = state_.recent || [];
    els.bodyList.innerHTML = rows.length ? rows.map(row => {
      const parts = [];
      if (row.weight_kg != null) parts.push(`${row.weight_kg}kg`);
      if (row.body_fat_pct != null) parts.push(`体脂 ${row.body_fat_pct}%`);
      Object.entries(state_.girth_labels || {}).forEach(([key, label]) => {
        if (row[key] != null) parts.push(`${label} ${row[key]}cm`);
      });
      return `<div class="tracker-item">
        <div><strong>${escapeHtml(row.occurred_on)}</strong><small>${escapeHtml(parts.join(' · ') || '只写了备注')}</small></div>
        <button data-body-delete="${row.id}">删除</button>
      </div>`;
    }).join('') : '<div class="today-empty">还没有身体指标记录。</div>';
    els.bodyList.querySelectorAll('[data-body-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteBody(Number(button.dataset.bodyDelete)));
    });
  }

  async function onSaveBody() {
    if (state.busy) return;
    const payload = {
      occurred_on: els.bodyDate.value || todayISO(),
      weight_kg: numberOrNull(els.bodyWeightInput.value),
      body_fat_pct: numberOrNull(els.bodyFatInput.value),
      waist_cm: numberOrNull(els.bodyWaistInput.value),
      chest_cm: numberOrNull(els.bodyChestInput.value),
      arm_cm: numberOrNull(els.bodyArmInput.value),
      note: els.bodyNoteInput.value.trim(),
    };
    state.busy = true;
    els.bodyStatus.hidden = true;
    try {
      const response = await api.saveBody(payload);
      state.body = response.body;
      [els.bodyWeightInput, els.bodyFatInput, els.bodyWaistInput,
       els.bodyChestInput, els.bodyArmInput, els.bodyNoteInput].forEach(input => { input.value = ''; });
      renderBody();
    } catch (error) {
      els.bodyStatus.textContent = cleanError(error, '保存失败');
      els.bodyStatus.hidden = false;
    } finally { state.busy = false; }
  }

  async function onDeleteBody(id) {
    if (state.busy || !window.confirm('删除这一天的身体指标？')) return;
    state.busy = true;
    try {
      state.body = (await api.delBody(id)).body;
      renderBody();
    } finally { state.busy = false; }
  }

  // ---------- 训练记录 ----------
  function renderTraining() {
    const training = state.training || {};
    const sessions = training.recent_sessions || [];
    els.trainingWeekVolume.textContent = fmtInt(training.week?.volume || 0);

    els.setSession.innerHTML = sessions.length
      ? sessions.map(item => `<option value="${item.id}">${escapeHtml(item.occurred_on)} · ${fmtInt(item.duration_minutes)} 分钟</option>`).join('')
      : '<option value="">先在上面记一次健身</option>';
    els.setExercise.innerHTML = (training.exercises || [])
      .map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join('');

    els.trainingList.innerHTML = sessions.length ? sessions.map(session => {
      const sets = (session.sets || []).map(set => {
        const parts = [];
        if (set.reps != null && set.weight_kg != null) parts.push(`${set.reps} × ${set.weight_kg}kg`);
        else if (set.reps != null) parts.push(`${set.reps} 次`);
        if (set.distance_km != null) parts.push(`${set.distance_km}km`);
        if (set.duration_seconds != null) parts.push(`${Math.round(set.duration_seconds / 60)} 分钟`);
        return `<div class="set-row">
          <span>${set.set_number}. ${escapeHtml(set.exercise_name)}</span>
          <em>${escapeHtml(parts.join(' · '))}</em>
          <button data-set-delete="${set.id}">×</button>
        </div>`;
      }).join('');
      return `<div class="training-session">
        <div class="training-session__head">
          <strong>${escapeHtml(session.occurred_on)}</strong>
          <span>${fmtInt(session.duration_minutes)} 分钟 · 容量 ${fmtInt(session.volume)}kg</span>
        </div>
        ${sets || '<div class="today-empty">这次训练还没有记录具体组数。</div>'}
      </div>`;
    }).join('') : '<div class="today-empty">还没有训练记录。</div>';

    els.trainingList.querySelectorAll('[data-set-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteSet(Number(button.dataset.setDelete)));
    });

    const records = training.records || [];
    els.recordsList.innerHTML = records.length ? records.map(record => {
      const bits = [];
      if (record.heaviest) bits.push(`最重 ${record.heaviest.weight_kg}kg × ${record.heaviest.reps}`);
      if (record.most_reps) bits.push(`最多 ${record.most_reps.reps} 次`);
      if (record.farthest) bits.push(`最远 ${record.farthest.distance_km}km`);
      if (record.estimated_one_rep_max) bits.push(`估算 1RM ${record.estimated_one_rep_max.value}kg`);
      return `<div class="record-row">
        <strong>${escapeHtml(record.exercise.name)}</strong>
        <span>${escapeHtml(bits.join(' · ') || '还没有可比较的组')}</span>
        <small>${fmtInt(record.set_count)} 组</small>
      </div>`;
    }).join('') : '<div class="today-empty">记下组数之后这里会出现个人纪录。</div>';
  }

  async function onAddSet() {
    if (state.busy) return;
    const sessionId = Number(els.setSession.value);
    if (!sessionId) { els.setStatus.textContent = '先在上面记一次健身，再往里加组'; els.setStatus.hidden = false; return; }
    const durationMinutes = numberOrNull(els.setDuration.value);
    state.busy = true;
    els.setStatus.hidden = true;
    try {
      const response = await api.addSet({
        session_id: sessionId,
        exercise_id: Number(els.setExercise.value),
        reps: numberOrNull(els.setReps.value),
        weight_kg: numberOrNull(els.setWeight.value),
        distance_km: numberOrNull(els.setDistance.value),
        duration_seconds: durationMinutes == null ? null : Math.round(durationMinutes * 60),
      });
      state.training = response.training;
      [els.setReps, els.setWeight, els.setDistance, els.setDuration].forEach(input => { input.value = ''; });
      renderTraining();
    } catch (error) {
      els.setStatus.textContent = cleanError(error, '这一组没能记下');
      els.setStatus.hidden = false;
    } finally { state.busy = false; }
  }

  async function onDeleteSet(id) {
    if (state.busy) return;
    state.busy = true;
    try {
      state.training = (await api.delSet(id)).training;
      renderTraining();
    } finally { state.busy = false; }
  }

  async function onAddExercise() {
    if (state.busy) return;
    const name = els.exerciseName.value.trim();
    if (!name) { els.exerciseName.focus(); return; }
    state.busy = true;
    els.setStatus.hidden = true;
    try {
      const response = await api.addExercise({ name, kind: els.exerciseKind.value });
      state.training = response.training;
      els.exerciseName.value = '';
      renderTraining();
    } catch (error) {
      els.setStatus.textContent = cleanError(error, '动作没能加入');
      els.setStatus.hidden = false;
    } finally { state.busy = false; }
  }

  // ---------- 收集箱 ----------
  function renderInbox() {
    const inbox = state.inbox || {};
    const summary = inbox.summary || {};
    els.inboxOpen.textContent = fmtInt(summary.open || 0);
    els.inboxFiled.textContent = fmtInt(summary.filed || 0);
    els.inboxOldest.textContent = summary.oldest_open_days == null ? '—' : `${summary.oldest_open_days} 天`;

    const targets = inbox.targets || {};
    const items = inbox.items || [];
    els.inboxList.innerHTML = items.length ? items.map(item => `
      <div class="inbox-item">
        <div class="inbox-item__text">${escapeHtml(item.content)}</div>
        <div class="inbox-item__actions">
          <select data-inbox-target="${item.id}" aria-label="归档到">
            ${Object.entries(targets).map(([key, label]) => `<option value="${key}">${escapeHtml(label)}</option>`).join('')}
          </select>
          <button data-inbox-file="${item.id}">归档</button>
          <button class="ghost" data-inbox-drop="${item.id}">丢弃</button>
        </div>
      </div>`).join('') : '<div class="today-empty">收集箱是空的。</div>';

    els.inboxList.querySelectorAll('[data-inbox-file]').forEach(button => {
      button.addEventListener('click', () => onFileInbox(Number(button.dataset.inboxFile)));
    });
    els.inboxList.querySelectorAll('[data-inbox-drop]').forEach(button => {
      button.addEventListener('click', () => onDropInbox(Number(button.dataset.inboxDrop)));
    });
  }

  async function onAddInbox() {
    if (state.busy) return;
    const content = els.inboxInput.value.trim();
    if (!content) { els.inboxInput.focus(); return; }
    state.busy = true;
    els.inboxStatus.hidden = true;
    try {
      state.inbox = (await api.addInbox({ content })).inbox;
      els.inboxInput.value = '';
      renderInbox();
    } catch (error) {
      els.inboxStatus.textContent = cleanError(error, '没能放进收集箱');
      els.inboxStatus.hidden = false;
    } finally { state.busy = false; }
  }

  async function onFileInbox(id) {
    if (state.busy) return;
    const select = els.inboxList.querySelector(`[data-inbox-target="${id}"]`);
    state.busy = true;
    try {
      state.inbox = (await api.fileInbox(id, { target_module: select.value })).inbox;
      renderInbox();
    } finally { state.busy = false; }
  }

  async function onDropInbox(id) {
    if (state.busy || !window.confirm('丢弃这条？这不代表这件事没发生过，只是不进任何模块。')) return;
    state.busy = true;
    try {
      state.inbox = (await api.dropInbox(id)).inbox;
      renderInbox();
    } finally { state.busy = false; }
  }

  // ---------- 洞察 ----------
  // 这里全部是同期变化，措辞上绝不出现因果。
  function renderInsights() {
    const insights = state.insights;
    if (insights) {
      els.insightsNote.textContent = insights.note;
      els.insightsList.innerHTML = insights.comparisons.map(item => {
        const hasNumber = item.correlation != null;
        const strength = hasNumber ? Math.abs(item.correlation) : 0;
        const label = !hasNumber ? '暂不给数字'
          : `${item.direction} · 相关系数 ${item.correlation}`;
        return `<div class="insight-row${hasNumber ? '' : ' is-muted'}">
          <div class="insight-row__pair">
            <strong>${escapeHtml(item.metric_a.label)}</strong>
            <span>与</span>
            <strong>${escapeHtml(item.metric_b.label)}</strong>
          </div>
          <div class="insight-row__value">${escapeHtml(label)}</div>
          <div class="insight-bar"><i style="width:${Math.round(strength * 100)}%"></i></div>
          <small>${escapeHtml(item.reason || `配对 ${item.paired_days} 天`)}</small>
        </div>`;
      }).join('');
    }

    const health = state.dataHealth;
    if (health) {
      els.healthMetricList.innerHTML = health.metrics.map(item => `
        <div class="stat">
          <span class="muted">${escapeHtml(item.label)}</span>
          <span>${item.days_since == null ? '从未记录' : `${item.days_since} 天前 · 近 ${item.window} 天记了 ${item.days_recorded} 天`}</span>
        </div>`).join('');
    }

    const tags = state.tagOverview;
    if (tags) {
      els.tagsList.innerHTML = tags.tags.length ? tags.tags.map(tag => `
        <div class="tag-row">
          <strong>#${escapeHtml(tag.name)}</strong>
          <span>${fmtInt(tag.total)} 条 · ${escapeHtml(tag.modules.map(key => tags.modules[key] || key).join('、')) || '无'}</span>
          ${tag.dead_links ? `<em class="tag-dead">${tag.dead_links} 条失效</em>` : ''}
        </div>`).join('') : '<div class="today-empty">还没有标签。标签可以横跨多个模块，用来把一件事的所有痕迹串起来。</div>';
    }
  }

  async function reloadInsights() {
    const days = Number(els.insightsDays.value) || 90;
    const [insights, health, tags] = await Promise.all([
      api.insights(days), api.dataHealth(), api.tagOverview(),
    ]);
    state.insights = insights;
    state.dataHealth = health;
    state.tagOverview = tags;
    renderInsights();
  }

  // ---------- 运动数据导入 ----------
  function renderHealthImport() {
    const preview = state.healthImportPreview;
    if (!preview) {
      els.healthSummary.hidden = true;
      els.healthPreview.innerHTML = '';
      els.btnCommitHealth.disabled = true;
      els.btnCommitHealth.textContent = '确认写入 0 条';
      return;
    }
    const parsed = preview.summary || {};
    const recon = preview.reconciliation?.summary || {};
    els.healthSummary.hidden = false;
    els.healthSummary.innerHTML = `<div class="statement-stats">
      <span><em>${escapeHtml(preview.kind_label || '')}</em>${parsed.date_from ? ` ${escapeHtml(parsed.date_from)} 至 ${escapeHtml(parsed.date_to)}` : ''}</span>
      <span>解析 <strong>${fmtInt(parsed.parsed || 0)}</strong> 条</span>
      <span>已经记过 <strong>${fmtInt(recon.matched || 0)}</strong> 条</span>
      <span class="is-new">还没记 <strong>${fmtInt(recon.new || 0)}</strong> 条</span>
      ${parsed.skipped ? `<span class="is-skip">跳过 <strong>${fmtInt(parsed.skipped)}</strong> 条</span>` : ''}
    </div>`;

    const rows = preview.reconciliation?.new || [];
    els.healthPreview.innerHTML = rows.length
      ? rows.map(row => `<div class="statement-row">
          <span>${escapeHtml(row.occurred_on)}</span>
          <span class="statement-row__note">${escapeHtml(row.note || (row.weight_kg != null ? `${row.weight_kg}kg` : '身体指标'))}</span>
          <em>${row.duration_minutes ? `${row.duration_minutes} 分钟` : ''}</em>
        </div>`).join('')
      : '<div class="today-empty">这份文件里的每一条都已经记过了。</div>';
    els.btnCommitHealth.disabled = rows.length === 0;
    els.btnCommitHealth.textContent = `确认写入 ${fmtInt(rows.length)} 条`;
  }

  function numberOrNull(value) {
    const text = String(value ?? '').trim();
    if (!text) return null;
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function cleanError(error, fallback) {
    return String(error?.message || fallback).replace(/^\d+\s*/, '');
  }

  // ---------- 番茄钟 ----------
  //
  // 网页这边只负责显示。剩余时间由后端按「结束时刻 − 当前时间」算，
  // 每秒本地重算一次也是同样的算法——不做自减，否则标签页切到后台
  // 被浏览器限流之后，倒计时会越走越慢。
  let focusTicker = null;

  function formatClock(totalSeconds) {
    const safe = Math.max(0, Math.round(totalSeconds));
    const minutes = String(Math.floor(safe / 60)).padStart(2, '0');
    const seconds = String(safe % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
  }

  function stopFocusTicker() {
    if (focusTicker) { clearInterval(focusTicker); focusTicker = null; }
  }

  function renderFocus() {
    const focus = state.focus || {};
    const running = focus.running;
    const today = focus.today || {};

    els.focusToday.textContent = today.count
      ? `今天完成 ${fmtInt(today.count)} 个，共 ${fmtInt(today.minutes)} 分钟`
      : '今天还没有完成的番茄。';

    els.focusIdle.hidden = !!running;
    els.focusRunning.hidden = !running;
    stopFocusTicker();

    if (!running) {
      els.focusTime.textContent = formatClock((els.focusMinutes.value || 25) * 60);
      els.focusMeta.textContent = '还没有开始';
      els.focusTime.classList.remove('is-done');
      return;
    }

    // 用结束时刻算，而不是从后端拿到的秒数往下减
    const endsAt = new Date(running.ends_at).getTime();
    const paint = () => {
      const remaining = (endsAt - Date.now()) / 1000;
      els.focusTime.textContent = formatClock(remaining);
      els.focusTime.classList.toggle('is-done', remaining <= 0);
      els.focusMeta.textContent = remaining > 0
        ? `${running.kind_label}${running.subject ? ' · ' + running.subject : ''} · 计划 ${fmtInt(running.planned_minutes)} 分钟`
        : `${running.kind_label}已经到点，结束它来记录`;
    };
    paint();
    focusTicker = setInterval(paint, 1000);
  }

  async function refreshFocus() {
    state.focus = await api.focusState();
    renderFocus();
  }

  async function onStartFocus(kind, minutes) {
    if (state.busy) return;
    state.busy = true;
    els.focusStatus.hidden = true;
    try {
      const response = await api.startFocus({
        kind,
        minutes: minutes || Number(els.focusMinutes.value) || null,
        subject: kind === 'focus' ? els.focusSubject.value.trim() : '',
      });
      state.focus = response.focus;
      renderFocus();
    } catch (error) {
      els.focusStatus.textContent = cleanError(error, '没能开始');
      els.focusStatus.hidden = false;
    } finally { state.busy = false; }
  }

  async function onFinishFocus(record) {
    const running = state.focus?.running;
    if (state.busy || !running) return;
    state.busy = true;
    els.focusStatus.hidden = true;
    try {
      const response = await api.finishFocus(running.id, {
        focus: Number(els.focusRating.value) || 3,
        record,
      });
      state.focus = response.focus;
      state.study = response.study;
      const session = response.session;
      els.focusStatus.textContent = session.recorded_study_session
        ? `已记下 ${fmtInt(session.actual_minutes)} 分钟`
        : `没有记入学习时长（${session.actual_minutes < 1 ? '不足一分钟' : '你选择了不记'}）`;
      els.focusStatus.hidden = false;
      renderFocus();
      renderStudy();
    } catch (error) {
      els.focusStatus.textContent = cleanError(error, '没能结束');
      els.focusStatus.hidden = false;
    } finally { state.busy = false; }
  }

  function renderToday() {
    const today = state.today || {};
    const monthStatusLabels = { unset: '尚未设置月预算', safe: '预算节奏正常', warning: '预算已接近上限', over: '本月已经超出预算' };
    els.todayHero.className = `today-hero is-${today.tone || 'neutral'}`;
    els.todayHeadline.textContent = today.headline || '正在读取真实账本…';
    els.todayDate.textContent = today.date || todayISO();
    els.todayAvailable.textContent = today.available_today == null ? '—' : fmtCNY(today.available_today);
    els.todayBudgetBasis.textContent = today.suggested_daily_budget == null
      ? '设置月预算或学期预算后计算'
      : `今日总建议 ${fmtCNY(today.suggested_daily_budget)}`;
    els.todaySpent.textContent = fmtCNY(today.today_expense);
    els.todayMonthRemaining.textContent = today.monthly_budget_remaining == null ? '—' : fmtCNY(today.monthly_budget_remaining);
    els.todayMonthStatus.textContent = monthStatusLabels[today.monthly_budget_status] || '等待预算数据';
    els.todayNextAllowance.textContent = today.next_allowance_date || '—';
    els.todayNextBalance.textContent = today.next_allowance_date
      ? `${fmtInt(today.days_until_next_allowance)} 天 · 到账前预计 ${fmtCNY(today.projected_balance_before_allowance)}`
      : '在规划中心设置生活费周期';

    const bills = today.upcoming_bills || [];
    els.todayReminders.innerHTML = bills.length ? bills.map(bill => `
      <div class="today-list-item"><div><strong>${escapeHtml(bill.name)}</strong><small>${bill.status === 'overdue' ? '已逾期' : `${fmtInt(bill.days_until_due)} 天后`} · ${escapeHtml(bill.account_name || '')}</small></div><em>${fmtCNY(bill.amount)}</em></div>
    `).join('') : '<div class="today-empty">未来 7 天没有待处理的固定账单。</div>';
    const goals = today.goals || [];
    els.todayGoals.innerHTML = goals.length ? goals.map(goal => `
      <div class="today-list-item"><div><strong>${escapeHtml(goal.name)}</strong><small>已预留 ${fmtCNY(goal.saved_amount)} · ${Number(goal.progress_rate || 0).toFixed(1)}%</small></div><em>${fmtCNY(goal.target_amount)}</em></div>
    `).join('') : '<div class="today-empty">暂时没有储蓄目标。</div>';

    const semester = today.semester || {};
    if (!semester.configured) {
      els.todaySemester.innerHTML = '<div class="today-empty">前往规划中心设置学期起止日期和总预算，系统会把月预算与学期预算取更谨慎的额度。</div>';
    } else {
      const mode = semester.mode === 'vacation' ? '寒暑假模式' : '在校模式';
      els.todaySemester.innerHTML = `<div class="today-semester-card"><strong>${mode} · ${escapeHtml(semester.start_date)} 至 ${escapeHtml(semester.end_date)}</strong><p>学期已过 ${Number(semester.elapsed_rate || 0).toFixed(1)}%，预算已使用 ${Number(semester.usage_rate || 0).toFixed(1)}%。</p><div class="today-semester-metrics"><div><span>剩余预算</span><em>${fmtCNY(semester.remaining_budget)}</em></div><div><span>建议日预算</span><em>${fmtCNY(semester.recommended_daily_budget)}</em></div></div></div>`;
    }
  }

  function renderDashboard() {
    const monthly = state.monthly || {};
    const totalBalance = state.accounts.reduce((sum, account) => sum + Number(account.balance || 0), 0);
    els.dashTotalBalance.textContent = fmtCNY(totalBalance);
    els.dashAccountCount.textContent = `${state.accounts.length} 个账户`;
    els.dashFamily.textContent = fmtCNY(monthly.family_support);
    els.dashIndependent.textContent = fmtCNY(monthly.independent_income);
    els.dashAutonomy.textContent = monthly.autonomy_coverage_rate == null
      ? '自主覆盖 —'
      : `自主覆盖 ${Number(monthly.autonomy_coverage_rate).toFixed(1)}%`;
    els.dashExpense.textContent = fmtCNY(monthly.total_expense);
    els.dashNet.textContent = `净现金流 ${fmtSignedCNY(monthly.net_cashflow)}`;
    els.dashMonthLabel.textContent = `${monthly.month || ''} · 按分类查看`;
    renderAccounts();
    renderCategoryBars();
    renderTrend();
    renderTransfers();
  }

  function renderBudgetStatus() {
    const budgetStatus = state.planning?.budget_status || {};
    const categories = budgetStatus.categories || [];
    const overallStatus = budgetStatus.total_status || 'unset';
    els.budgetOverall.classList.toggle('is-warning', overallStatus === 'warning');
    els.budgetOverall.classList.toggle('is-over', overallStatus === 'over');
    els.budgetOverall.textContent = overallStatus === 'unset'
      ? '尚未设置月预算'
      : `${Number(budgetStatus.total_usage_rate || 0).toFixed(1)}% · 剩余 ${fmtCNY(budgetStatus.total_remaining)}`;
    els.budgetList.innerHTML = categories.map(item => {
      const usage = item.usage_rate == null ? 0 : Math.max(0, Math.min(Number(item.usage_rate), 100));
      const statusClass = item.status === 'over' ? 'is-over' : (item.status === 'warning' ? 'is-warning' : '');
      const usageLabel = item.usage_rate == null ? '未设预算' : `${Number(item.usage_rate).toFixed(1)}%`;
      return `
        <div class="budget-row ${statusClass}">
          <span>${CATEGORY_LABELS[item.category] || '其他'}</span>
          <div class="budget-row__meter">
            <small><span>已花 ${fmtCNY(item.actual)}</span><span>${usageLabel}</span></small>
            <div class="budget-row__bar"><i style="width:${usage.toFixed(1)}%"></i></div>
          </div>
          <div class="plan-money-input"><i>¥</i><input data-budget-category="${item.category}" type="number" min="0" step="0.01" value="${Number(item.budget || 0) || ''}" placeholder="预算"></div>
        </div>
      `;
    }).join('');
  }

  function renderPlanning() {
    const planning = state.planning || {};
    const settings = planning.settings || {};
    const forecast = planning.forecast || {};
    const goals = planning.goals || [];
    const basisLabels = {
      monthly_budget: '按每月支出预算估算',
      current_month_pace: '按本月真实花销速度估算',
      ledger_average: '按账本历史日均花销估算',
      no_sample: '尚无支出样本，暂不扣减',
    };

    els.planMonthEnd.textContent = fmtCNY(forecast.projected_month_end_balance);
    els.planMonthEnd.classList.toggle('is-negative', Number(forecast.projected_month_end_balance) < 0);
    els.planMonthEndNote.textContent = `预计还会支出 ${fmtCNY(forecast.projected_remaining_expense)}`;
    els.planNextDate.textContent = forecast.next_allowance_date || '—';
    els.planNextBalance.textContent = `到账前预计 ${fmtCNY(forecast.projected_balance_before_allowance)} · ${fmtInt(forecast.days_until_next_allowance)} 天`;
    els.planGoalAllocated.textContent = fmtCNY(forecast.allocated_to_goals);
    els.planUnallocated.textContent = `尚未分配 ${fmtCNY(forecast.unallocated_balance)}`;
    els.planDailyRate.textContent = fmtCNY(forecast.daily_spending_rate);
    els.planSpendingBasis.textContent = basisLabels[forecast.spending_basis] || '等待预测数据';
    renderBudgetStatus();

    const semester = planning.semester || {};
    const semesterStatusLabels = { unset: '尚未设置', upcoming: '尚未开始', active: semester.mode === 'vacation' ? '假期进行中' : '学期进行中', completed: '本期已结束' };
    els.semesterBadge.textContent = semesterStatusLabels[semester.status] || '尚未设置';
    els.semesterBadge.className = semester.pace_status === 'over' ? 'is-over' : (semester.pace_status === 'warning' ? 'is-warning' : (semester.configured ? 'is-active' : ''));
    els.semesterActual.textContent = fmtCNY(semester.actual_expense);
    els.semesterRemaining.textContent = semester.remaining_budget == null ? '—' : fmtCNY(semester.remaining_budget);
    els.semesterDaily.textContent = semester.recommended_daily_budget == null ? '—' : fmtCNY(semester.recommended_daily_budget);
    els.semesterProgress.style.width = `${Math.max(0, Math.min(Number(semester.usage_rate || 0), 100)).toFixed(1)}%`;
    els.semesterCopy.textContent = semester.configured
      ? `${semester.mode === 'vacation' ? '寒暑假' : '在校'} · 已过 ${Number(semester.elapsed_rate || 0).toFixed(1)}% · 还剩 ${fmtInt(semester.remaining_days)} 天`
      : '设置后会结合真实支出计算学期进度。';
    if (document.activeElement !== els.semesterStart) els.semesterStart.value = semester.start_date || '';
    if (document.activeElement !== els.semesterEnd) els.semesterEnd.value = semester.end_date || '';
    if (document.activeElement !== els.semesterBudget) els.semesterBudget.value = Number(semester.total_budget || 0) || '';
    if (document.activeElement !== els.semesterMode) els.semesterMode.value = semester.mode || 'in_school';

    if (document.activeElement !== els.planAllowanceAmount) {
      els.planAllowanceAmount.value = Number(settings.monthly_allowance_amount || 0) || '';
    }
    if (document.activeElement !== els.planBudget) {
      els.planBudget.value = Number(settings.monthly_spending_budget || 0) || '';
    }
    els.planAllowanceDay.value = String(settings.allowance_day || 1);

    if (!goals.length) {
      els.goalList.innerHTML = '<div class="goal-empty">还没有储蓄目标。先从一个真正想实现的小目标开始。</div>';
      return;
    }
    els.goalList.innerHTML = goals.map(goal => {
      const progress = Math.max(0, Math.min(Number(goal.progress_rate || 0), 100));
      const targetDate = goal.target_date ? `目标日 ${escapeHtml(goal.target_date)}` : '未设置目标日期';
      return `
        <article class="goal-card">
          <div class="goal-card__head">
            <div><strong>${escapeHtml(goal.name)}</strong><small>${targetDate} · 目标 ${fmtCNY(goal.target_amount)}</small></div>
            <em>${Number(goal.progress_rate || 0).toFixed(1)}%</em>
          </div>
          <div class="goal-progress"><i style="width:${progress.toFixed(1)}%"></i></div>
          <div class="goal-card__actions">
            <input data-goal-saved="${goal.id}" type="number" min="0" step="0.01" value="${Number(goal.saved_amount || 0)}" aria-label="${escapeHtml(goal.name)}已预留金额">
            <button data-goal-update="${goal.id}">更新预留</button>
            <button data-goal-delete="${goal.id}" aria-label="删除${escapeHtml(goal.name)}">删除</button>
          </div>
        </article>
      `;
    }).join('');
    els.goalList.querySelectorAll('[data-goal-update]').forEach(button => {
      button.addEventListener('click', () => onUpdateGoal(Number(button.dataset.goalUpdate)));
    });
    els.goalList.querySelectorAll('[data-goal-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteGoal(Number(button.dataset.goalDelete)));
    });
  }

  function parseCSV(text) {
    const rows = [];
    let row = [];
    let cell = '';
    let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (quoted) {
        if (char === '"' && text[index + 1] === '"') { cell += '"'; index += 1; }
        else if (char === '"') quoted = false;
        else cell += char;
      } else if (char === '"') quoted = true;
      else if (char === ',') { row.push(cell); cell = ''; }
      else if (char === '\n' || char === '\r') {
        if (char === '\r' && text[index + 1] === '\n') index += 1;
        row.push(cell); cell = '';
        if (row.some(value => String(value).trim() !== '')) rows.push(row);
        row = [];
      } else cell += char;
    }
    row.push(cell);
    if (row.some(value => String(value).trim() !== '')) rows.push(row);
    return rows;
  }

  function normalizeImportDate(raw) {
    const match = String(raw || '').trim().replace(/[./]/g, '-').match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const candidate = new Date(year, month - 1, day);
    if (candidate.getFullYear() !== year || candidate.getMonth() !== month - 1 || candidate.getDate() !== day) return null;
    return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  async function readStatementFile(file) {
    const bytes = await file.arrayBuffer();
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (_) {
      return new TextDecoder('gb18030').decode(bytes);
    }
  }

  function analyzeStatement(fileName, text) {
    const parsed = parseCSV(text);
    if (parsed.length < 2) throw new Error('CSV 至少需要表头和一行账目');
    const aliases = {
      date: ['date', '日期', '交易日期', 'occurred_on'],
      type: ['type', '类型', '收支', '收支类型', '交易类型'],
      amount: ['amount', '金额', '交易金额'],
      category: ['category', '分类', '支出分类'],
      source: ['source', '来源', '收入来源'],
      note: ['note', '备注', '摘要', '交易说明'],
      account: ['account', '账户', '账户名称'],
    };
    const headers = parsed[0].map(value => String(value || '').replace(/^\uFEFF/, '').trim().toLowerCase());
    const indexes = {};
    Object.entries(aliases).forEach(([key, names]) => {
      indexes[key] = headers.findIndex(header => names.includes(header));
    });
    if (indexes.date < 0 || indexes.amount < 0) throw new Error('CSV 必须包含日期/date 和金额/amount 两列');

    const categoryMap = Object.fromEntries(Object.entries(CATEGORY_LABELS).flatMap(([key, label]) => [[key, key], [label, key]]));
    const sourceMap = Object.fromEntries(Object.entries(SOURCE_LABELS).flatMap(([key, label]) => [[key, key], [label, key]]));
    const accountMap = new Map(state.accounts.map(account => [account.name.trim().toLowerCase(), account.id]));
    const defaultAccountId = Number(els.importAccount.value);
    const valueAt = (row, key) => indexes[key] >= 0 ? String(row[indexes[key]] || '').trim() : '';
    const rows = [];

    parsed.slice(1).forEach((rawRow, rowIndex) => {
      const errors = [];
      const occurredOn = normalizeImportDate(valueAt(rawRow, 'date'));
      if (!occurredOn) errors.push('日期格式应为 YYYY-MM-DD');
      let amountText = valueAt(rawRow, 'amount').replace(/[¥￥,\s]/g, '');
      if (/^\(.*\)$/.test(amountText)) amountText = `-${amountText.slice(1, -1)}`;
      const signedAmount = Number(amountText);
      if (!Number.isFinite(signedAmount) || signedAmount === 0) errors.push('金额必须是非零数字');
      const typeText = valueAt(rawRow, 'type').toLowerCase();
      let type = null;
      if (['income', '收入', '入账', '入'].includes(typeText)) type = 'income';
      if (['expense', '支出', '消费', '出账', '出'].includes(typeText)) type = 'expense';
      if (!type && signedAmount < 0) type = 'expense';
      if (!type) errors.push('请填写收入或支出类型');

      const categoryText = valueAt(rawRow, 'category');
      const sourceText = valueAt(rawRow, 'source');
      let category = type === 'expense' ? (categoryMap[categoryText] || 'other') : null;
      let source = type === 'income' ? (sourceMap[sourceText] || 'family_support') : null;
      if (categoryText && !categoryMap[categoryText]) errors.push(`未知支出分类：${categoryText}`);
      if (sourceText && !sourceMap[sourceText]) errors.push(`未知收入来源：${sourceText}`);

      const accountText = valueAt(rawRow, 'account');
      const accountId = accountText ? accountMap.get(accountText.toLowerCase()) : defaultAccountId;
      if (!accountId) errors.push(accountText ? `找不到账户：${accountText}` : '没有可用的默认账户');
      rows.push({
        line: rowIndex + 2,
        occurred_on: occurredOn,
        type,
        amount: Math.abs(signedAmount || 0),
        category,
        source,
        account_id: accountId,
        account_name: accountText || state.accounts.find(account => account.id === accountId)?.name || '',
        note: valueAt(rawRow, 'note'),
        errors,
      });
    });
    const validRows = rows.filter(row => row.errors.length === 0).map(({ line, account_name, errors, ...row }) => row);
    return { fileName, rows, validRows, errorCount: rows.length - validRows.length };
  }

  // ---------- 微信 / 支付宝账单对账 ----------
  // 账单是权威事实，但「对不上」只表示账本里没有匹配的记录，
  // 不能推导这笔钱一定没记，所以一律要用户确认后才写入。
  function renderStatementPreview() {
    const preview = state.statementPreview;
    if (!preview) {
      els.statementSummary.hidden = true;
      els.statementPreview.innerHTML = '';
      els.btnCommitStatement.disabled = true;
      els.btnCommitStatement.textContent = '确认写入 0 笔';
      return;
    }

    const parsed = preview.summary || {};
    const recon = preview.reconciliation?.summary || {};
    els.statementSummary.hidden = false;
    els.statementSummary.classList.remove('is-error');
    els.statementSummary.innerHTML = `
      <div class="statement-stats">
        <span><em>${escapeHtml(preview.source_label || '')}</em>${parsed.date_from ? ` ${escapeHtml(parsed.date_from)} 至 ${escapeHtml(parsed.date_to)}` : ''}</span>
        <span>解析 <strong>${fmtInt(parsed.parsed || 0)}</strong> 条</span>
        <span>已经记过 <strong>${fmtInt(recon.matched || 0)}</strong> 条</span>
        <span class="is-new">还没记 <strong>${fmtInt(recon.new || 0)}</strong> 条 · ${fmtCNY(recon.new_amount || 0)}</span>
        ${parsed.review ? `<span class="is-review">需要你判断 <strong>${fmtInt(parsed.review)}</strong> 条</span>` : ''}
        ${parsed.skipped ? `<span class="is-skip">跳过 <strong>${fmtInt(parsed.skipped)}</strong> 条</span>` : ''}
      </div>`;

    const rows = preview.reconciliation?.new || [];
    const skipped = preview.skipped || [];
    const parts = [];
    if (rows.length) {
      parts.push('<h4>将要写入</h4>' + rows.map(row => `
        <div class="statement-row">
          <span>${escapeHtml(row.occurred_on)}</span>
          <span class="statement-row__note">${escapeHtml(row.note)}</span>
          <em class="${row.type === 'income' ? 'is-income' : ''}">${row.type === 'income' ? '+' : '−'}${fmtCNY(row.amount)}</em>
        </div>`).join(''));
    } else {
      parts.push('<div class="today-empty">这份账单里的每一条都已经在账本里了，没有需要补录的。</div>');
    }
    // 方向认不出来的行不会自动写入，但也不能让它们悄悄消失——
    // 那正是「账目对不上却不知道少了哪几笔」的来源。
    const review = preview.review || [];
    if (review.length) {
      parts.push('<h4>需要你判断（不会自动写入）</h4>' + review.map(row => `
        <div class="statement-row statement-row--review">
          <span>${escapeHtml(row.occurred_on)}</span>
          <span class="statement-row__note">${escapeHtml(row.note)} — ${escapeHtml(row.reason)}</span>
          <em>${fmtCNY(row.amount)}</em>
        </div>`).join(''));
    }
    if (skipped.length) {
      parts.push('<h4>已跳过</h4>' + skipped.map(item => `
        <div class="statement-row statement-row--skip">
          <span>第 ${fmtInt(item.line)} 行</span>
          <span class="statement-row__note">${escapeHtml(item.reason)}</span>
        </div>`).join(''));
    }
    els.statementPreview.innerHTML = parts.join('');

    els.btnCommitStatement.disabled = rows.length === 0;
    els.btnCommitStatement.textContent = `确认写入 ${fmtInt(rows.length)} 笔`;
  }

  function renderImportPreview() {
    const preview = state.importPreview;
    if (!preview) {
      els.importSummary.hidden = true;
      els.importPreview.innerHTML = '';
      els.btnCommitImport.disabled = true;
      els.btnCommitImport.textContent = '确认导入 0 笔';
      return;
    }
    els.importSummary.hidden = false;
    els.importSummary.classList.toggle('is-error', preview.errorCount > 0);
    els.importSummary.textContent = preview.errorCount > 0
      ? `共 ${preview.rows.length} 行，其中 ${preview.errorCount} 行需要修正；本次不会导入任何内容。`
      : `校验通过：${preview.validRows.length} 笔账目等待确认。`;
    els.importPreview.innerHTML = `
      <table class="import-table">
        <thead><tr><th>行</th><th>日期</th><th>类型</th><th>金额</th><th>账户</th><th>结果</th></tr></thead>
        <tbody>${preview.rows.slice(0, 20).map(row => `
          <tr class="${row.errors.length ? 'is-error' : ''}">
            <td>${row.line}</td><td>${row.occurred_on || '—'}</td><td>${row.type === 'income' ? '收入' : (row.type === 'expense' ? '支出' : '—')}</td>
            <td>${fmtCNY(row.amount)}</td><td>${escapeHtml(row.account_name || '—')}</td><td>${row.errors.length ? escapeHtml(row.errors.join('；')) : '可导入'}</td>
          </tr>`).join('')}</tbody>
      </table>`;
    els.btnCommitImport.disabled = preview.errorCount > 0 || preview.validRows.length === 0;
    els.btnCommitImport.textContent = `确认导入 ${preview.validRows.length} 笔`;
  }

  function renderImportHistory() {
    els.importHistory.innerHTML = state.importBatches.map(batch => `
      <div class="import-batch">
        <div><strong>${escapeHtml(batch.filename)}</strong><small>${String(batch.created_at || '').slice(0, 19).replace('T', ' ')}</small></div>
        <em>${fmtInt(batch.remaining_rows)} / ${fmtInt(batch.row_count)} 笔</em>
        <button data-import-batch-delete="${batch.id}">撤销整批</button>
      </div>
    `).join('');
    els.importHistory.querySelectorAll('[data-import-batch-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteImportBatch(Number(button.dataset.importBatchDelete)));
    });
  }

  function renderMonthlyReview() {
    const calendar = state.calendar || {};
    const bills = calendar.bills || [];
    const summary = calendar.summary || {};
    const review = calendar.review || {};
    const alertCount = Number(summary.overdue_count || 0) + Number(summary.due_soon_count || 0);
    els.reviewNet.textContent = fmtSignedCNY(review.net_cashflow);
    els.reviewNet.classList.toggle('is-negative', Number(review.net_cashflow) < 0);
    els.reviewTxCount.textContent = `${fmtInt(review.transaction_count)} 笔交易`;
    els.reviewExpense.textContent = fmtCNY(review.total_expense);
    els.reviewExpenseChange.textContent = review.expense_change_rate == null
      ? '暂无上月支出样本'
      : `较上月${Number(review.expense_change_rate) >= 0 ? '增加' : '减少'} ${Math.abs(Number(review.expense_change_rate)).toFixed(1)}%`;
    els.reviewBills.textContent = fmtCNY(summary.unpaid_amount);
    els.reviewBillCount.textContent = `${fmtInt(summary.unpaid_count)} 项待支付`;
    els.reviewAlerts.textContent = fmtInt(alertCount);
    els.billCalendarMonth.textContent = `${calendar.month || ''} · 每月固定支出`;
    els.reviewTopCategory.textContent = review.top_expense_category
      ? `${CATEGORY_LABELS[review.top_expense_category] || '其他'} ${fmtCNY(review.top_expense_amount)}`
      : '—';
    els.reviewSavingRate.textContent = review.savings_rate == null ? '—' : `${Number(review.savings_rate).toFixed(1)}%`;
    els.reviewScheduled.textContent = fmtCNY(summary.scheduled_amount);
    const observations = review.observations || ['本月尚无足够数据生成复盘。'];
    els.reviewObservations.innerHTML = observations.map(text => `<div class="review-observation">${escapeHtml(text)}</div>`).join('');

    const billsByDay = new Map();
    bills.forEach(bill => {
      const day = Number(bill.day_of_month);
      if (!billsByDay.has(day)) billsByDay.set(day, []);
      billsByDay.get(day).push(bill);
    });
    const today = new Date();
    const currentMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
    const cells = [];
    for (let blank = 0; blank < Number(calendar.first_weekday || 0); blank += 1) {
      cells.push('<div class="calendar-day is-empty" aria-hidden="true"></div>');
    }
    for (let day = 1; day <= Number(calendar.days_in_month || 0); day += 1) {
      const dayBills = billsByDay.get(day) || [];
      const isToday = calendar.month === currentMonth && day === today.getDate();
      cells.push(`
        <div class="calendar-day ${isToday ? 'is-today' : ''}">
          <span class="calendar-day__number">${day}</span>
          ${dayBills.map(bill => `<span class="calendar-bill ${bill.is_paid ? 'is-paid' : ''} ${bill.status === 'overdue' ? 'is-overdue' : ''}" title="${escapeHtml(bill.name)} · ${fmtCNY(bill.amount)}">${escapeHtml(bill.name)}</span>`).join('')}
        </div>`);
    }
    els.billCalendarGrid.innerHTML = cells.join('');

    if (!bills.length) {
      els.billList.innerHTML = '<div class="goal-empty">还没有固定账单。创建提醒不会自动产生支出。</div>';
      return;
    }
    const statusLabels = { paid: '已支付', overdue: '已逾期', due_soon: '三日内到期', upcoming: '待支付' };
    els.billList.innerHTML = bills.map(bill => `
      <div class="bill-item ${bill.status === 'overdue' ? 'is-overdue' : ''} ${bill.status === 'due_soon' ? 'is-due-soon' : ''}">
        <div class="bill-item__day">${bill.day_of_month}<small>每月</small></div>
        <div><strong>${escapeHtml(bill.name)} · ${fmtCNY(bill.amount)}</strong><span>${CATEGORY_LABELS[bill.category] || '其他'} · ${escapeHtml(bill.account_name)} · ${statusLabels[bill.status] || '待支付'}</span></div>
        <div class="bill-item__actions">
          ${bill.is_paid
            ? `<button data-bill-unpay="${bill.id}">撤销支付</button>`
            : `<button data-bill-pay="${bill.id}">记为已支付</button>`}
          <button data-bill-delete="${bill.id}">删除提醒</button>
        </div>
      </div>`).join('');
    els.billList.querySelectorAll('[data-bill-pay]').forEach(button => {
      button.addEventListener('click', () => onPayBill(Number(button.dataset.billPay)));
    });
    els.billList.querySelectorAll('[data-bill-unpay]').forEach(button => {
      button.addEventListener('click', () => onUnpayBill(Number(button.dataset.billUnpay)));
    });
    els.billList.querySelectorAll('[data-bill-delete]').forEach(button => {
      button.addEventListener('click', () => onDeleteBill(Number(button.dataset.billDelete)));
    });
  }

  function renderDataCenter() {
    const report = state.annualReport || { summary: {}, monthly: [], expense_categories: [] };
    const summary = report.summary || {};
    const searchSummary = state.searchResult?.summary || {};
    els.annualIncome.textContent = fmtCNY(summary.total_income);
    els.annualActiveMonths.textContent = `${fmtInt(summary.active_months)} 个活跃月份`;
    els.annualExpense.textContent = fmtCNY(summary.total_expense);
    els.annualTxCount.textContent = `${fmtInt(summary.transaction_count)} 笔交易`;
    els.annualNet.textContent = fmtSignedCNY(summary.net_cashflow);
    els.annualNet.classList.toggle('is-negative', Number(summary.net_cashflow) < 0);
    els.annualSavingRate.textContent = summary.savings_rate == null ? '储蓄率 —' : `储蓄率 ${Number(summary.savings_rate).toFixed(1)}%`;
    els.searchCount.textContent = fmtInt(searchSummary.count);
    els.searchNet.textContent = `净额 ${fmtSignedCNY(searchSummary.net)}`;

    const months = report.monthly || [];
    const maxValue = Math.max(...months.flatMap(item => [Number(item.income), Number(item.expense)]), 1);
    els.annualChart.innerHTML = months.map(item => {
      const incomeHeight = Number(item.income) > 0 ? Math.max(3, Number(item.income) / maxValue * 100) : 0;
      const expenseHeight = Number(item.expense) > 0 ? Math.max(3, Number(item.expense) / maxValue * 100) : 0;
      return `<div class="annual-month" title="${item.month} · 收入 ${fmtCNY(item.income)} · 支出 ${fmtCNY(item.expense)}">
        <div class="annual-month__bars"><i class="annual-month__income" style="height:${incomeHeight.toFixed(1)}%"></i><i class="annual-month__expense" style="height:${expenseHeight.toFixed(1)}%"></i></div>
        <span>${item.month.slice(5)}月</span></div>`;
    }).join('');
    const best = report.best_cashflow_month;
    const highest = report.highest_expense_month;
    els.annualBestMonth.textContent = best ? `${best.month} ${fmtSignedCNY(best.net_cashflow)}` : '—';
    els.annualHighestExpense.textContent = highest ? `${highest.month} ${fmtCNY(highest.expense)}` : '—';
    els.annualIncomeMix.textContent = `${fmtCNY(summary.family_support)} / ${fmtCNY(summary.independent_income)}`;
    els.annualCategories.innerHTML = (report.expense_categories || []).length
      ? report.expense_categories.map(item => `<span class="annual-category">${CATEGORY_LABELS[item.category] || '其他'} ${fmtCNY(item.amount)}</span>`).join('')
      : '<span class="annual-category">本年度尚无支出分类数据</span>';

    const results = state.searchResult?.transactions || [];
    els.searchSummary.textContent = `共 ${fmtInt(searchSummary.count)} 笔 · 收入 ${fmtCNY(searchSummary.income)} · 支出 ${fmtCNY(searchSummary.expense)} · 净额 ${fmtSignedCNY(searchSummary.net)}`;
    els.searchResults.innerHTML = results.length ? `
      <table class="search-table"><thead><tr><th>日期</th><th>类型</th><th>账户</th><th>分类 / 来源</th><th>备注</th><th>金额</th></tr></thead>
      <tbody>${results.map(tx => {
        const label = tx.type === 'income' ? (SOURCE_LABELS[tx.source] || '家庭生活费') : (CATEGORY_LABELS[tx.category] || '其他');
        return `<tr><td>${tx.occurred_on}</td><td>${tx.type === 'income' ? '收入' : '支出'}</td><td>${escapeHtml(tx.account_name || '未分配')}</td><td>${escapeHtml(label)}</td><td>${escapeHtml(tx.note || '')}</td><td class="search-amount--${tx.type}">${tx.type === 'income' ? '+' : '−'}${fmtCNY(tx.amount)}</td></tr>`;
      }).join('')}</tbody></table>` : '<div class="goal-empty">没有符合条件的交易。</div>';
  }

  async function refreshDataCenterData() {
    const year = parseInt(els.annualYear.value, 10) || new Date().getFullYear();
    const [annual, search] = await Promise.all([
      api.annualReport(year),
      api.searchTransactions(currentSearchParams()),
    ]);
    state.annualReport = annual;
    state.searchResult = search;
    renderDataCenter();
  }

  function renderTxList() {
    const items = state.transactions;
    els.txCount.textContent = items.length;
    els.txList.classList.toggle('is-empty', items.length === 0);
    els.txItems.innerHTML = '';
    const frag = document.createDocumentFragment();
    for (const t of items) {
      const li = document.createElement('li');
      const incomeKind = t.type === 'income'
        ? (t.source === 'family_support' ? 'family' : 'independent')
        : 'expense';
      const sourceLabel = t.type === 'income'
        ? (SOURCE_LABELS[t.source] || '家庭生活费')
        : (CATEGORY_LABELS[t.category] || '其他');
      const accountLabel = t.account_name || '未分配账户';
      li.className = `tx-item tx-item--${t.type} tx-item--${incomeKind}`;
      li.innerHTML = `
        <span class="tx-item__bar"></span>
        <div class="tx-item__main">
          <div class="tx-item__note">${escapeHtml(t.note) || (t.type === 'income' ? '收入' : '支出')}</div>
          <div class="tx-item__date"><span class="tx-item__source">${escapeHtml(accountLabel)}</span><span class="tx-item__source">${escapeHtml(sourceLabel)}</span>${t.occurred_on}</div>
        </div>
        <div class="tx-item__amount">${t.type === 'income' ? '+' : '−'}${fmtCNY(t.amount)}</div>
        <button class="tx-item__del" title="删除" aria-label="删除交易">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        </button>
      `;
      li.querySelector('.tx-item__del').addEventListener('click', () => onDelete(t.id));
      frag.appendChild(li);
    }
    els.txItems.appendChild(frag);
  }

  const escapeHtml = (s) => String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]);

  function renderLifeOverview() {
    const life = state.life || {};
    const finance = life.finance || {};
    const fitness = life.fitness || state.fitness || {};
    const nutrition = life.nutrition || state.nutrition || {};
    const recovery = life.recovery || state.recovery || {};
    const study = life.study || state.study || {};
    const rhythm = life.rhythm || state.rhythm || {};
    const fitnessToday = fitness.today || {};
    const fitnessWeek = fitness.week || {};
    const nutritionToday = nutrition.today || {};
    const recoveryToday = recovery.today || null;
    const studyToday = study.today || {};
    const studyWeek = study.week || {};
    const taskSummary = rhythm.task_summary || {};
    const habitSummary = rhythm.habit_summary || {};
    els.lifeDate.textContent = life.date ? `${life.date} · 把零散的生活，收进一个属于自己的地方。` : '把零散的生活，收进一个属于自己的地方。';
    els.lifeHeadline.textContent = life.headline || '从一条真实记录开始今天';
    els.lifeCompleted.textContent = life.completed_signals || 0;
    els.lifeBalance.textContent = fmtCNY(finance.current_balance || 0);
    els.lifeFinanceNote.textContent = Number(finance.today_expense || 0) > 0
      ? `今天已支出 ${fmtCNY(finance.today_expense)}`
      : '今天尚未记录支出';
    els.lifeFitnessMinutes.textContent = fmtInt(fitnessToday.minutes || 0);
    els.lifeFitnessNote.textContent = `本周 ${fitnessWeek.count || 0} 次 · ${fitnessWeek.minutes || 0} 分钟`;
    els.lifeMealCount.textContent = nutritionToday.count || 0;
    els.lifeNutritionNote.textContent = nutritionToday.count
      ? `已知蛋白质 ${nutritionToday.protein_g || 0}g · 饮水 ${nutritionToday.water_ml || 0}ml`
      : '今天尚未记录饮食';
    els.lifeSleepHours.textContent = recoveryToday?.sleep_hours == null ? '—' : `${recoveryToday.sleep_hours} 小时`;
    els.lifeRecoveryNote.textContent = recoveryToday
      ? `精力 ${recoveryToday.energy ?? '—'} · 心情 ${recoveryToday.mood ?? '—'}`
      : '今天尚未记录状态';
    els.lifeStudyMinutes.textContent = fmtInt(studyToday.minutes || 0);
    els.lifeStudyNote.textContent = studyToday.count
      ? `今天 ${studyToday.count} 次 · 专注度 ${studyToday.avg_focus ?? '—'}`
      : `本周 ${studyWeek.count || 0} 次 · ${studyWeek.minutes || 0} 分钟`;
    const rhythmCompleted = (taskSummary.today_done || 0) + (habitSummary.completed_today || 0);
    const rhythmTotal = (taskSummary.today_total || 0) + (habitSummary.total || 0);
    els.lifeRhythmProgress.textContent = `${rhythmCompleted} / ${rhythmTotal}`;
    els.lifeRhythmNote.textContent = taskSummary.overdue
      ? `${taskSummary.overdue} 项待办已逾期`
      : (rhythmTotal ? `待办与习惯共 ${rhythmTotal} 项` : '还没有待办或习惯');
    const actions = life.actions || [];
    els.lifeActions.innerHTML = actions.length
      ? actions.map((item, index) => `
          <button class="life-action" data-action-module="${escapeHtml(item.module)}">
            <span class="life-action__index">${String(index + 1).padStart(2, '0')}</span>
            <span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span>
          </button>`).join('')
      : '<div class="life-action life-action--complete"><span class="life-action__index">✓</span><span><strong>今天的基础记录已经齐了</strong><small>继续生活就好，不必为了数据而记录。</small></span></div>';
    els.lifeActions.querySelectorAll('[data-action-module]').forEach(button => {
      button.addEventListener('click', () => switchModule(button.dataset.actionModule));
    });
  }

  function renderFitness() {
    const fitness = state.fitness || {};
    const today = fitness.today || {};
    const week = fitness.week || {};
    els.fitnessTodayMinutes.textContent = fmtInt(today.minutes || 0);
    els.fitnessTodayCount.textContent = `${today.count || 0} 次记录`;
    els.fitnessWeekMinutes.textContent = fmtInt(week.minutes || 0);
    els.fitnessWeekCount.textContent = `${week.count || 0} 次记录`;
    els.fitnessWeekIntensity.textContent = week.avg_intensity == null ? '—' : `${week.avg_intensity} / 10`;
    const items = fitness.recent || [];
    els.fitnessList.innerHTML = items.length ? items.map(item => `
      <article class="tracker-entry">
        <span class="tracker-entry__mark">${escapeHtml(ACTIVITY_LABELS[item.activity] || '动')}</span>
        <div><strong>${escapeHtml(item.note || ACTIVITY_LABELS[item.activity] || '身体活动')}</strong><small>${escapeHtml(item.occurred_on)} · ${item.duration_minutes} 分钟 · 强度 ${item.intensity}</small></div>
        <button data-delete-workout="${item.id}" aria-label="删除健身记录" title="删除">×</button>
      </article>`).join('') : '<div class="tracker-empty"><p>还没有健身记录<br><small>完成一次散步或拉伸后，就从这里开始。</small></p></div>';
    els.fitnessList.querySelectorAll('[data-delete-workout]').forEach(button => {
      button.addEventListener('click', () => onDeleteWorkout(Number(button.dataset.deleteWorkout)));
    });
  }

  function renderNutrition() {
    const nutrition = state.nutrition || {};
    const today = nutrition.today || {};
    els.nutritionTodayCount.textContent = today.count || 0;
    els.nutritionCalories.textContent = fmtInt(today.calories || 0);
    els.nutritionCaloriesNote.textContent = today.calories_known ? `${today.calories_known} 条记录包含热量` : '尚无可汇总数值';
    els.nutritionProtein.textContent = Number(today.protein_g || 0).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
    els.nutritionWater.textContent = fmtInt(today.water_ml || 0);
    const items = nutrition.recent || [];
    els.nutritionList.innerHTML = items.length ? items.map(item => {
      const facts = [];
      if (item.calories != null) facts.push(`${item.calories} kcal`);
      if (item.protein_g != null) facts.push(`蛋白质 ${item.protein_g}g`);
      if (item.water_ml != null) facts.push(`饮水 ${item.water_ml}ml`);
      return `<article class="tracker-entry">
        <span class="tracker-entry__mark">${escapeHtml(MEAL_LABELS[item.meal_type] || '食')}</span>
        <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.occurred_on)}${facts.length ? ` · ${facts.join(' · ')}` : ' · 未填写营养数值'}</small></div>
        <button data-delete-nutrition="${item.id}" aria-label="删除饮食记录" title="删除">×</button>
      </article>`;
    }).join('') : '<div class="tracker-empty"><p>还没有饮食记录<br><small>营养数值可以不填，先记下吃了什么。</small></p></div>';
    els.nutritionList.querySelectorAll('[data-delete-nutrition]').forEach(button => {
      button.addEventListener('click', () => onDeleteNutrition(Number(button.dataset.deleteNutrition)));
    });
  }

  function renderRecovery() {
    const recovery = state.recovery || {};
    const today = recovery.today || null;
    const latest = recovery.latest || null;
    const week = recovery.week || {};
    els.recoveryLatestSleep.textContent = latest?.sleep_hours == null ? '—' : `${latest.sleep_hours} 小时`;
    els.recoveryLatestDate.textContent = latest ? `${latest.occurred_on} · 最近一次记录` : '尚未记录';
    els.recoveryWeekSleep.textContent = week.sleep_hours == null ? '—' : `${week.sleep_hours} 小时`;
    els.recoveryWeekCount.textContent = `${week.sleep_known || 0} 天填写了睡眠`;
    els.recoveryTodayState.textContent = today ? `${today.energy ?? '—'} / ${today.mood ?? '—'}` : '—';
    const selectedDate = els.recoveryDate.value || todayISO();
    const selected = (recovery.recent || []).find(item => item.occurred_on === selectedDate) || null;
    els.recoverySleepHours.value = selected?.sleep_hours ?? '';
    els.recoverySleepQuality.value = selected?.sleep_quality ?? '';
    els.recoveryEnergy.value = selected?.energy ?? '';
    els.recoveryMood.value = selected?.mood ?? '';
    els.recoveryNote.value = selected?.note ?? '';
    els.btnSaveRecovery.textContent = selected ? '更新这一天的恢复记录' : '保存这一天的恢复记录';
    const items = recovery.recent || [];
    els.recoveryList.innerHTML = items.length ? items.map(item => {
      const facts = [];
      if (item.sleep_hours != null) facts.push(`睡眠 ${item.sleep_hours}h`);
      if (item.sleep_quality != null) facts.push(`感受 ${item.sleep_quality}/5`);
      if (item.energy != null) facts.push(`精力 ${item.energy}/5`);
      if (item.mood != null) facts.push(`心情 ${item.mood}/5`);
      return `<article class="tracker-entry">
        <span class="tracker-entry__mark">眠</span>
        <div><strong>${escapeHtml(item.note || '每日恢复记录')}</strong><small>${escapeHtml(item.occurred_on)} · ${facts.join(' · ') || '仅记录了备注'}</small></div>
        <button data-delete-recovery="${item.id}" aria-label="删除恢复记录" title="删除">×</button>
      </article>`;
    }).join('') : '<div class="tracker-empty"><p>还没有恢复记录<br><small>睡眠、精力或心情，任选一项开始即可。</small></p></div>';
    els.recoveryList.querySelectorAll('[data-delete-recovery]').forEach(button => {
      button.addEventListener('click', () => onDeleteRecovery(Number(button.dataset.deleteRecovery)));
    });
  }

  function renderStudy() {
    const study = state.study || {};
    const today = study.today || {};
    const week = study.week || {};
    els.studyTodayMinutes.textContent = fmtInt(today.minutes || 0);
    els.studyTodayCount.textContent = `${today.count || 0} 次记录`;
    els.studyWeekMinutes.textContent = fmtInt(week.minutes || 0);
    els.studyWeekCount.textContent = `${week.count || 0} 次记录`;
    els.studyWeekFocus.textContent = week.avg_focus == null ? '—' : `${week.avg_focus} / 5`;
    const items = study.recent || [];
    els.studyList.innerHTML = items.length ? items.map(item => `
      <article class="tracker-entry">
        <span class="tracker-entry__mark">学</span>
        <div><strong>${escapeHtml(item.subject)}</strong><small>${escapeHtml(item.occurred_on)} · ${item.duration_minutes} 分钟 · 专注度 ${item.focus}/5${item.note ? ` · ${escapeHtml(item.note)}` : ''}</small></div>
        <button data-delete-study="${item.id}" aria-label="删除学习记录" title="删除">×</button>
      </article>`).join('') : '<div class="tracker-empty"><p>还没有学习记录<br><small>完成一段专注后，再来记下投入的时间。</small></p></div>';
    els.studyList.querySelectorAll('[data-delete-study]').forEach(button => {
      button.addEventListener('click', () => onDeleteStudy(Number(button.dataset.deleteStudy)));
    });
  }

  function renderRhythm() {
    const rhythm = state.rhythm || {};
    const taskSummary = rhythm.task_summary || {};
    const habitSummary = rhythm.habit_summary || {};
    els.rhythmTaskProgress.textContent = `${taskSummary.today_done || 0} / ${taskSummary.today_total || 0}`;
    els.rhythmTaskNote.textContent = taskSummary.today_total
      ? `${taskSummary.today_pending || 0} 项尚未完成`
      : '今天还没有待办';
    els.rhythmOverdue.textContent = taskSummary.overdue || 0;
    els.rhythmHabitProgress.textContent = `${habitSummary.completed_today || 0} / ${habitSummary.total || 0}`;
    els.rhythmHabitNote.textContent = habitSummary.total
      ? `${habitSummary.pending_today || 0} 个习惯今天尚未打卡`
      : '还没有每日习惯';

    const todayKey = rhythm.date || state.life?.date || todayISO();
    const tasks = rhythm.tasks || [];
    els.taskList.innerHTML = tasks.length ? tasks.map(task => {
      const overdue = task.status === 'pending' && task.due_on < todayKey;
      const dateLabel = task.due_on === todayKey ? '今天' : (overdue ? `逾期 · ${task.due_on}` : task.due_on);
      return `<article class="rhythm-item${task.status === 'done' ? ' is-done' : ''}${overdue ? ' is-overdue' : ''}">
        <button class="rhythm-check${task.status === 'done' ? ' is-checked' : ''}" data-toggle-task="${task.id}" aria-label="${task.status === 'done' ? '恢复未完成' : '完成待办'}">${task.status === 'done' ? '✓' : ''}</button>
        <div class="rhythm-item__body"><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(dateLabel)} · ${escapeHtml(RHYTHM_CATEGORY_LABELS[task.category] || '其他')} · ${escapeHtml(TASK_PRIORITY_LABELS[task.priority] || '普通')}优先级</small></div>
        <div class="rhythm-item__actions"><button class="rhythm-delete" data-delete-task="${task.id}" aria-label="删除待办" title="删除">×</button></div>
      </article>`;
    }).join('') : '<div class="rhythm-empty"><p>还没有待办<br><small>从今天最具体的一件事开始。</small></p></div>';

    const habits = rhythm.habits || [];
    els.habitList.innerHTML = habits.length ? habits.map(habit => `
      <article class="rhythm-item${habit.checked_today ? ' is-done' : ''}">
        <button class="rhythm-check${habit.checked_today ? ' is-checked' : ''}" data-toggle-habit="${habit.id}" aria-label="${habit.checked_today ? '取消今日习惯打卡' : '完成今日习惯打卡'}">${habit.checked_today ? '✓' : ''}</button>
        <div class="rhythm-item__body"><strong>${escapeHtml(habit.name)}</strong><small>${escapeHtml(RHYTHM_CATEGORY_LABELS[habit.category] || '其他')} · 累计 ${habit.checkin_count || 0} 天</small></div>
        <div class="rhythm-item__actions"><span class="rhythm-streak">连续 ${habit.streak || 0} 天</span><button class="rhythm-delete" data-archive-habit="${habit.id}" aria-label="归档习惯" title="归档">×</button></div>
      </article>`).join('') : '<div class="rhythm-empty"><p>还没有每日习惯<br><small>习惯用于重复实践，不是强制待办。</small></p></div>';

    els.taskList.querySelectorAll('[data-toggle-task]').forEach(button => button.addEventListener('click', () => onToggleTask(Number(button.dataset.toggleTask))));
    els.taskList.querySelectorAll('[data-delete-task]').forEach(button => button.addEventListener('click', () => onDeleteTask(Number(button.dataset.deleteTask))));
    els.habitList.querySelectorAll('[data-toggle-habit]').forEach(button => button.addEventListener('click', () => onToggleHabit(Number(button.dataset.toggleHabit))));
    els.habitList.querySelectorAll('[data-archive-habit]').forEach(button => button.addEventListener('click', () => onArchiveHabit(Number(button.dataset.archiveHabit))));
  }

  function renderReflection() {
    const reflection = state.reflection || {};
    const selected = reflection.selected || null;
    const weekly = reflection.weekly || {};
    const finance = weekly.finance || {};
    const fitness = weekly.fitness || {};
    const nutrition = weekly.nutrition || {};
    const recovery = weekly.recovery || {};
    const study = weekly.study || {};
    const rhythm = weekly.rhythm || {};
    const week = weekly.week || {};
    if (reflection.date && els.reflectionDate.value !== reflection.date) els.reflectionDate.value = reflection.date;
    els.reflectionHighlight.value = selected?.highlight || '';
    els.reflectionChallenge.value = selected?.challenge || '';
    els.reflectionGratitude.value = selected?.gratitude || '';
    els.reflectionNote.value = selected?.note || '';
    els.btnSaveReflection.textContent = selected ? '更新这一天的回顾' : '保存这一天的回顾';
    els.reflectionWeekRange.textContent = week.start_date && week.end_date
      ? `${week.start_date} — ${week.end_date}`
      : '本周';
    els.reflectionWeekExpense.textContent = fmtCNY(finance.expense || 0);
    els.reflectionWeekFitness.textContent = `${fmtInt(fitness.minutes || 0)} 分钟`;
    els.reflectionWeekFitnessNote.textContent = `本周 ${fitness.count || 0} 次`;
    els.reflectionWeekStudy.textContent = `${fmtInt(study.minutes || 0)} 分钟`;
    els.reflectionWeekStudyNote.textContent = `本周 ${study.count || 0} 次${study.avg_focus == null ? '' : ` · 专注 ${study.avg_focus}/5`}`;
    els.reflectionWeekSleep.textContent = recovery.sleep_hours == null ? '—' : `${recovery.sleep_hours} 小时`;
    els.reflectionWeekSleepNote.textContent = recovery.sleep_known
      ? `${recovery.sleep_known} 天填写了睡眠`
      : '尚无睡眠记录';
    els.reflectionWeekFinanceDetail.textContent = `${finance.transaction_count || 0} 笔 · 收入 ${fmtCNY(finance.income || 0)}`;
    els.reflectionWeekNutritionDetail.textContent = `${nutrition.count || 0} 次 · 饮水 ${fmtInt(nutrition.water_ml || 0)}ml`;
    els.reflectionWeekRecoveryDetail.textContent = `精力 ${recovery.energy ?? '—'} · 心情 ${recovery.mood ?? '—'}`;
    els.reflectionWeekRhythmDetail.textContent = `待办 ${rhythm.tasks_done || 0} / ${rhythm.tasks_total || 0} · 习惯 ${rhythm.habit_checkins || 0} 次`;
    els.reflectionWeekReflectionCount.textContent = `本周已写 ${weekly.reflection_count || 0} 天`;
    const items = reflection.recent || [];
    els.reflectionList.innerHTML = items.length ? items.map(item => {
      const preview = item.highlight || item.challenge || item.gratitude || item.note || '每日回顾';
      const filled = [item.highlight, item.challenge, item.gratitude, item.note].filter(Boolean).length;
      return `<article class="tracker-entry">
        <span class="tracker-entry__mark">记</span>
        <div><strong>${escapeHtml(preview)}</strong><small>${escapeHtml(item.occurred_on)} · 填写了 ${filled} 项</small></div>
        <button data-delete-reflection="${item.id}" aria-label="删除每日回顾" title="删除">×</button>
      </article>`;
    }).join('') : '<div class="tracker-empty"><p>还没有回顾记录<br><small>亮点、困难、感谢或自由记录，任选一项开始。</small></p></div>';
    els.reflectionList.querySelectorAll('[data-delete-reflection]').forEach(button => {
      button.addEventListener('click', () => onDeleteReflection(Number(button.dataset.deleteReflection)));
    });
  }

  function renderLifeCalendar() {
    const calendar = state.lifeCalendar || {};
    const summary = calendar.summary || {};
    const selected = calendar.selected || { facts: [], arrangements: [] };
    const [year, month] = String(calendar.month || todayISO().slice(0, 7)).split('-').map(Number);
    els.lifeCalendarActiveDays.textContent = `${summary.active_days || 0} 天`;
    els.lifeCalendarFactCount.textContent = `${summary.fact_count || 0} 条`;
    els.lifeCalendarArrangementCount.textContent = `${summary.arrangement_count || 0} 项`;
    els.lifeCalendarMonthLabel.textContent = `${year} 年 ${month} 月`;
    const blanks = Array.from({ length: calendar.first_weekday || 0 }, () => '<div class="life-calendar-blank" aria-hidden="true"></div>').join('');
    const dayButtons = (calendar.days || []).map(day => {
      const dayNumber = Number(day.date.slice(-2));
      const selectedClass = day.date === calendar.selected_date ? ' is-selected' : '';
      const todayClass = day.date === calendar.today ? ' is-today' : '';
      const marks = (day.modules || []).map(module => `<i class="life-calendar-dot life-calendar-dot--${escapeHtml(module)}" title="${escapeHtml(LIFE_MODULE_LABELS[module] || module)}"></i>`).join('');
      const arrangementMark = day.arrangement_count ? '<i class="life-calendar-arrangement-mark" title="存在安排"></i>' : '';
      const countLabel = [day.fact_count ? `${day.fact_count}记` : '', day.arrangement_count ? `${day.arrangement_count}排` : ''].filter(Boolean).join(' · ');
      return `<button class="life-calendar-day${selectedClass}${todayClass}" data-life-calendar-date="${escapeHtml(day.date)}" aria-label="${escapeHtml(day.date)}，${day.fact_count || 0} 条事实，${day.arrangement_count || 0} 项安排">
        <span class="life-calendar-day__head"><span class="life-calendar-day__number">${dayNumber}</span><small class="life-calendar-day__counts">${countLabel}</small></span>
        <span class="life-calendar-day__marks">${marks}${arrangementMark}</span>
      </button>`;
    }).join('');
    els.lifeCalendarGrid.innerHTML = blanks + dayButtons;
    const selectedDate = calendar.selected_date || selected.date || todayISO();
    const dateObject = new Date(`${selectedDate}T12:00:00`);
    els.lifeCalendarSelectedDate.textContent = `${dateObject.getMonth() + 1} 月 ${dateObject.getDate()} 日 · 星期${'日一二三四五六'[dateObject.getDay()]}`;
    const facts = selected.facts || [];
    const arrangements = selected.arrangements || [];
    els.lifeCalendarDaySummary.textContent = `${facts.length} 条事实 · ${arrangements.length} 项安排`;
    const renderItems = (items, emptyText) => items.length ? items.map(item => `
      <button class="life-calendar-item" data-calendar-module="${escapeHtml(item.module)}">
        <span class="life-calendar-item__mark">${escapeHtml(LIFE_MODULE_LABELS[item.module] || '生')}</span>
        <span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span>
        <span class="life-calendar-item__jump">→</span>
      </button>`).join('') : `<div class="life-calendar-empty"><span>${escapeHtml(emptyText)}</span></div>`;
    els.lifeCalendarFacts.innerHTML = renderItems(facts, '这一天还没有已保存的生活事实');
    els.lifeCalendarArrangements.innerHTML = renderItems(arrangements, '这一天没有待办或固定账单安排');
    els.lifeCalendarGrid.querySelectorAll('[data-life-calendar-date]').forEach(button => {
      button.addEventListener('click', () => loadLifeCalendar(calendar.month, button.dataset.lifeCalendarDate));
    });
    [els.lifeCalendarFacts, els.lifeCalendarArrangements].forEach(container => {
      container.querySelectorAll('[data-calendar-module]').forEach(button => {
        button.addEventListener('click', () => switchModule(button.dataset.calendarModule));
      });
    });
  }

  function renderGoals() {
    const goalsState = state.goals || {};
    const summary = goalsState.summary || {};
    const goals = goalsState.goals || [];
    els.goalsActiveCount.textContent = `${summary.active || 0} 个`;
    els.goalsCompletedCount.textContent = `${summary.completed || 0} 个`;
    els.goalsMilestoneProgress.textContent = `${summary.milestones_done || 0} / ${summary.milestones_total || 0}`;
    els.goalsList.innerHTML = goals.length ? goals.map(goal => {
      const progress = goal.progress || { completed: 0, total: 0 };
      const progressPercent = progress.total ? Math.round(progress.completed / progress.total * 100) : 0;
      const actions = goal.status === 'active'
        ? `<button data-goal-status="paused" data-goal-id="${goal.id}">暂停</button><button data-goal-status="completed" data-goal-id="${goal.id}">标记完成</button>`
        : (goal.status === 'paused'
          ? `<button data-goal-status="active" data-goal-id="${goal.id}">继续</button><button data-goal-status="completed" data-goal-id="${goal.id}">标记完成</button>`
          : `<button data-goal-status="active" data-goal-id="${goal.id}">重新进行</button>`);
      const milestones = goal.milestones || [];
      return `<article class="goal-card is-${escapeHtml(goal.status)}">
        <div class="goal-card__head">
          <span class="goal-card__mark">标</span>
          <div class="goal-card__title"><strong>${escapeHtml(goal.title)}</strong><small>${escapeHtml(GOAL_CATEGORY_LABELS[goal.category] || '其他')} · ${escapeHtml(GOAL_STATUS_LABELS[goal.status] || goal.status)}${goal.target_date ? ` · 目标日期 ${escapeHtml(goal.target_date)}` : ''}</small></div>
          <div class="goal-card__actions">${actions}<button class="goal-delete" data-delete-life-goal="${goal.id}">删除</button></div>
        </div>
        ${goal.motivation ? `<p class="goal-card__motivation">${escapeHtml(goal.motivation)}</p>` : ''}
        <div class="goal-progress"><span class="goal-progress__track"><i class="goal-progress__fill" style="width:${progressPercent}%"></i></span><small>${progress.completed} / ${progress.total} 个里程碑</small></div>
        <div class="goal-milestones">${milestones.length ? milestones.map(milestone => `
          <div class="goal-milestone${milestone.status === 'done' ? ' is-done' : ''}">
            <button class="goal-milestone__check${milestone.status === 'done' ? ' is-checked' : ''}" data-toggle-goal-milestone="${milestone.id}" aria-label="${milestone.status === 'done' ? '恢复未完成' : '完成里程碑'}">${milestone.status === 'done' ? '✓' : ''}</button>
            <div><strong>${escapeHtml(milestone.title)}</strong><small>${milestone.target_date ? `日期 ${escapeHtml(milestone.target_date)}` : '未设置日期'}</small></div>
            <button class="goal-milestone__delete" data-delete-goal-milestone="${milestone.id}" aria-label="删除里程碑">×</button>
          </div>`).join('') : '<div class="goal-milestone goal-milestone--empty"><small>还没有里程碑；可以把目标拆成几个可识别的阶段结果。</small></div>'}</div>
        <div class="goal-milestone-create" data-goal-milestone-form="${goal.id}">
          <input type="text" maxlength="100" placeholder="新增一个里程碑" data-goal-milestone-title="${goal.id}" aria-label="里程碑名称">
          <input type="date" data-goal-milestone-date="${goal.id}" aria-label="里程碑日期">
          <button data-add-goal-milestone="${goal.id}">添加</button>
        </div>
      </article>`;
    }).join('') : '<div class="goals-empty"><p>还没有生活目标<br><small>从一个真正想靠近的方向开始，不需要一次规划整个人生。</small></p></div>';
    els.goalsList.querySelectorAll('[data-goal-status]').forEach(button => {
      button.addEventListener('click', () => onSetLifeGoalStatus(Number(button.dataset.goalId), button.dataset.goalStatus));
    });
    els.goalsList.querySelectorAll('[data-delete-life-goal]').forEach(button => {
      button.addEventListener('click', () => onDeleteLifeGoal(Number(button.dataset.deleteLifeGoal)));
    });
    els.goalsList.querySelectorAll('[data-toggle-goal-milestone]').forEach(button => {
      button.addEventListener('click', () => onToggleGoalMilestone(Number(button.dataset.toggleGoalMilestone)));
    });
    els.goalsList.querySelectorAll('[data-delete-goal-milestone]').forEach(button => {
      button.addEventListener('click', () => onDeleteGoalMilestone(Number(button.dataset.deleteGoalMilestone)));
    });
    els.goalsList.querySelectorAll('[data-add-goal-milestone]').forEach(button => {
      button.addEventListener('click', () => onAddGoalMilestone(Number(button.dataset.addGoalMilestone)));
    });
  }

  function renderLifeSearch() {
    const search = state.lifeSearch || {};
    const results = search.results || [];
    const total = search.summary?.total || 0;
    els.lifeSearchSummary.textContent = search.query
      ? `“${search.query}”找到 ${total} 条结果${search.truncated ? ' · 当前显示前 100 条' : ''}`
      : '输入关键词开始搜索';
    els.lifeSearchResults.innerHTML = search.query
      ? (results.length ? results.map(item => `
          <button class="life-search-result" data-life-search-module="${escapeHtml(item.module)}">
            <span class="life-search-result__mark">${escapeHtml(LIFE_MODULE_LABELS[item.module] || '生')}</span>
            <span class="life-search-result__body"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span>
            <span class="life-search-result__meta">${escapeHtml(LIFE_MODULE_NAMES[item.module] || item.module)}<br>${escapeHtml(item.date || '长期')} · ${escapeHtml(LIFE_SEARCH_KIND_LABELS[item.kind] || item.kind)}</span>
          </button>`).join('')
        : '<div class="life-search-empty">没有匹配结果。可以换一个更短的关键词或清除筛选。</div>')
      : '<div class="life-search-empty">可以搜索记录正文、显示名称、分类和金额。</div>';
    els.lifeSearchResults.querySelectorAll('[data-life-search-module]').forEach(button => {
      button.addEventListener('click', () => {
        closeLifeSearch();
        switchModule(button.dataset.lifeSearchModule);
      });
    });
  }

  function openLifeSearch() {
    els.lifeSearchOverlay.hidden = false;
    els.lifeSearchStatus.hidden = true;
    setTimeout(() => els.lifeSearchInput.focus(), 30);
  }

  function closeLifeSearch() {
    els.lifeSearchOverlay.hidden = true;
  }

  async function runLifeSearch() {
    const query = els.lifeSearchInput.value.trim();
    if (!query) {
      els.lifeSearchStatus.textContent = '请输入要查找的关键词。';
      els.lifeSearchStatus.hidden = false;
      els.lifeSearchInput.focus();
      return;
    }
    els.btnRunLifeSearch.disabled = true;
    els.lifeSearchStatus.hidden = true;
    try {
      state.lifeSearch = await api.lifeSearch({
        q: query,
        module: els.lifeSearchModule.value,
        date_from: els.lifeSearchDateFrom.value,
        date_to: els.lifeSearchDateTo.value,
        limit: 100,
      });
      renderLifeSearch();
    } catch (error) {
      els.lifeSearchStatus.textContent = error.message || '搜索失败，原数据没有改变。';
      els.lifeSearchStatus.hidden = false;
    } finally {
      els.btnRunLifeSearch.disabled = false;
    }
  }

  function renderAll() {
    renderLifeOverview();
    renderLifeCalendar();
    renderGoals();
    renderCapture();
    renderBody();
    renderFocus();
    renderTraining();
    renderInbox();
    renderInsights();
    renderHealthImport();
    renderLifeSearch();
    renderFitness();
    renderNutrition();
    renderRecovery();
    renderStudy();
    renderRhythm();
    renderReflection();
    renderProgress();
    renderStats();
    renderAccountSelect();
    renderToday();
    renderDashboard();
    renderPlanning();
    renderImportPreview();
    renderStatementPreview();
    renderImportHistory();
    renderMonthlyReview();
    renderDataCenter();
    renderTxList();
  }

  // ============================================
  // 交互编排
  // ============================================
  async function loadAndPaint() {
    const reportYear = parseInt(els.annualYear.value, 10) || new Date().getFullYear();
    const [data, annual, search, lifeCalendar] = await Promise.all([
      api.state(),
      api.annualReport(reportYear),
      api.searchTransactions({ limit: 200 }),
      api.lifeCalendar(),
    ]);
    state.settings = data.settings;
    state.stats = data.stats;
    state.accounts = data.accounts || [];
    state.monthly = data.monthly || null;
    state.transfers = data.transfers || [];
    state.planning = data.planning || { settings: {}, goals: [], forecast: {} };
    state.today = data.today || {};
    state.life = data.life || {};
    state.fitness = data.fitness || { today: {}, week: {}, recent: [] };
    state.nutrition = data.nutrition || { today: {}, recent: [] };
    state.recovery = data.recovery || { today: null, latest: null, week: {}, recent: [] };
    state.study = data.study || { today: {}, week: {}, recent: [] };
    state.rhythm = data.rhythm || { tasks: [], task_summary: {}, habits: [], habit_summary: {} };
    state.reflection = data.reflection || { date: '', selected: null, weekly: {}, recent: [] };
    state.lifeCalendar = lifeCalendar || { month: '', selected_date: '', days: [], summary: {}, selected: {} };
    state.goals = data.goals || { goals: [], summary: {} };
    state.capture = data.capture || { pending: [], summary: {}, channel_labels: {} };
    const [bodyState, trainingState, inboxState, focusState] = await Promise.all([
      api.bodyState(), api.trainingState(), api.inboxState(), api.focusState(),
    ]);
    state.body = bodyState;
    state.focus = focusState;
    state.training = trainingState;
    state.inbox = inboxState;
    state.importBatches = data.import_batches || [];
    state.calendar = data.calendar || { bills: [], summary: {}, review: {} };
    state.annualReport = annual;
    state.searchResult = search;
    state.transactions = data.transactions;
    const serverDate = data.life?.date || data.today?.date || todayISO();
    els.fitnessDate.value = serverDate;
    els.nutritionDate.value = serverDate;
    els.recoveryDate.value = serverDate;
    els.studyDate.value = serverDate;
    els.taskDue.value = serverDate;
    els.reflectionDate.value = state.reflection.date || serverDate;
    txDP.setValue(serverDate);
    grid.setData(state.stats);
    renderAll();
    if (!state.settings) showOverlay();
  }

  function showOverlay() {
    els.overlay.hidden = false;
    birthDP.setValue(state.settings?.birth_date || '');
    els.cfgTargetAge.value = state.settings?.target_age || 80;
    els.cfgShowPast.checked = !!state.settings?.show_past;
    els.cfgTrackingDays.value = state.settings?.tracking_days_override || '';
    els.cfgAvgExpense.value = state.settings?.avg_daily_expense_override || '';
    els.modalTargetAgeDisplay.textContent = els.cfgTargetAge.value;
    setTimeout(() => birthDP.trigger.focus(), 80);
  }
  function hideOverlay() { els.overlay.hidden = true; }

  // 设置面板
  els.btnSettings.addEventListener('click', showOverlay);
  els.cfgCancel.addEventListener('click', () => { if (state.settings) hideOverlay(); });
  els.cfgTargetAge.addEventListener('input', e => {
    els.modalTargetAgeDisplay.textContent = e.target.value || '80';
  });
  function syncTransactionForm() {
    const isIncome = state.txType === 'income';
    els.incomeSourceField.hidden = !isIncome;
    els.expenseCategoryField.hidden = isIncome;
    els.expenseCategoryField.parentElement.classList.toggle('is-single', isIncome);
    state.txSource = els.txSource.value;
    const buttonLabel = !isIncome
      ? '记下花销'
      : (state.txSource === 'family_support' ? '记入生活支持' : '点亮自主星光');
    els.btnSubmit.querySelector('.btn__text').textContent = buttonLabel;
  }

  els.cfgSave.addEventListener('click', async () => {
    if (state.busy) return;
    const birth = birthDP.value;
    const age = parseInt(els.cfgTargetAge.value, 10) || 80;
    if (!birth) { birthDP.open(); return; }
    state.busy = true;
    try {
      const r = await api.settings({
        birth_date: birth,
        target_age: age,
        currency: 'CNY',
        show_past: !!els.cfgShowPast.checked,
        use_initial_assets: !!state.settings?.use_initial_assets,
        initial_assets: Number(state.settings?.initial_assets || 0),
        tracking_days_override: parseInt(els.cfgTrackingDays.value, 10) || 0,
        avg_daily_expense_override: parseFloat(els.cfgAvgExpense.value) || 0,
      });
      state.settings = r.settings;
      state.stats = r.stats;
      state.planning = r.planning || state.planning;
      grid.setData(state.stats);
      renderAll();
      hideOverlay();
    } finally { state.busy = false; }
  });

  // 类型分段切换
  els.segBtns.forEach(b => {
    b.addEventListener('click', () => {
      els.segBtns.forEach(x => {
        x.classList.toggle('is-active', x === b);
        x.setAttribute('aria-selected', x === b ? 'true' : 'false');
      });
      state.txType = b.dataset.type;
      syncTransactionForm();
    });
  });
  els.txSource.addEventListener('change', syncTransactionForm);
  syncTransactionForm();

  async function loadLifeCalendar(month = '', selectedDate = '') {
    els.lifeCalendarStatus.hidden = true;
    try {
      state.lifeCalendar = await api.lifeCalendar(month, selectedDate);
      renderLifeCalendar();
    } catch (error) {
      els.lifeCalendarStatus.textContent = error.message || '生活日历读取失败，原数据没有改变。';
      els.lifeCalendarStatus.hidden = false;
    }
  }

  function moveLifeCalendarMonth(delta) {
    const [year, month] = String(state.lifeCalendar?.month || todayISO().slice(0, 7)).split('-').map(Number);
    const target = new Date(year, month - 1 + delta, 1);
    const targetMonth = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`;
    const targetDate = todayISO().startsWith(targetMonth) ? todayISO() : `${targetMonth}-01`;
    loadLifeCalendar(targetMonth, targetDate);
  }

  function switchModule(module) {
    // 白名单要和 index.html 里的 data-module-panel 一一对应，漏一个那个导航就点不动
    const MODULES = ['overview', 'calendar', 'goals', 'finance', 'fitness', 'body',
                     'nutrition', 'recovery', 'study', 'rhythm', 'reflection', 'inbox', 'insights'];
    if (!MODULES.includes(module)) return;
    state.currentModule = module;
    els.modulePanels.forEach(panel => { panel.hidden = panel.dataset.modulePanel !== module; });
    els.moduleNav.forEach(button => {
      const active = button.dataset.moduleTarget === module;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (module === 'insights' && !state.insights) {
      reloadInsights().catch(() => { /* 面板里会显示空态，不打断切换 */ });
    }
    if (module === 'finance') {
      requestAnimationFrame(() => {
        grid.resize();
        if (state.currentView === 'grid') grid.resume();
      });
    } else {
      grid.pause();
    }
    if (module === 'calendar') loadLifeCalendar(state.lifeCalendar?.month, state.lifeCalendar?.selected_date);
  }
  els.moduleNav.forEach(button => button.addEventListener('click', () => switchModule(button.dataset.moduleTarget)));
  els.moduleJumps.forEach(button => button.addEventListener('click', () => switchModule(button.dataset.moduleJump)));
  els.lifeCalendarPrev.addEventListener('click', () => moveLifeCalendarMonth(-1));
  els.lifeCalendarNext.addEventListener('click', () => moveLifeCalendarMonth(1));
  els.lifeCalendarToday.addEventListener('click', () => loadLifeCalendar(todayISO().slice(0, 7), todayISO()));
  els.btnLifeSearch.addEventListener('click', openLifeSearch);
  els.btnCloseLifeSearch.addEventListener('click', closeLifeSearch);
  els.btnRunLifeSearch.addEventListener('click', runLifeSearch);
  els.btnResetLifeSearch.addEventListener('click', () => {
    els.lifeSearchModule.value = '';
    els.lifeSearchDateFrom.value = '';
    els.lifeSearchDateTo.value = '';
    if (els.lifeSearchInput.value.trim()) runLifeSearch();
  });
  els.lifeSearchInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); runLifeSearch(); }
  });
  els.lifeSearchOverlay.addEventListener('click', event => {
    if (event.target === els.lifeSearchOverlay) closeLifeSearch();
  });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (els.lifeSearchOverlay.hidden) openLifeSearch();
      else closeLifeSearch();
    } else if (event.key === 'Escape' && !els.lifeSearchOverlay.hidden) {
      closeLifeSearch();
    }
  });

  els.btnAddLifeGoal.addEventListener('click', async () => {
    const title = els.goalTitle.value.trim();
    if (!title) {
      els.goalsStatus.textContent = '请先填写目标名称。';
      els.goalsStatus.hidden = false;
      els.goalTitle.focus();
      return;
    }
    if (state.busy) return;
    state.busy = true;
    els.btnAddLifeGoal.disabled = true;
    els.goalsStatus.hidden = true;
    try {
      const response = await api.addLifeGoal({
        title,
        category: els.goalCategory.value,
        target_date: els.goalTargetDate.value || null,
        motivation: els.goalMotivation.value.trim(),
      });
      state.goals = response.goals;
      els.goalTitle.value = '';
      els.goalTargetDate.value = '';
      els.goalMotivation.value = '';
      els.goalsStatus.textContent = '生活目标已保存；完成状态仍由你主动确认。';
      els.goalsStatus.hidden = false;
      renderGoals();
    } catch (error) {
      els.goalsStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.goalsStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddLifeGoal.disabled = false;
    }
  });

  els.fitnessDate.value = todayISO();
  els.nutritionDate.value = todayISO();
  els.recoveryDate.value = todayISO();
  els.studyDate.value = todayISO();
  els.taskDue.value = todayISO();
  els.reflectionDate.value = todayISO();
  els.fitnessIntensity.addEventListener('input', () => { els.fitnessIntensityOutput.value = els.fitnessIntensity.value; });
  els.studyFocus.addEventListener('input', () => { els.studyFocusOutput.value = els.studyFocus.value; });
  els.recoveryDate.addEventListener('change', renderRecovery);
  els.reflectionDate.addEventListener('change', async () => {
    const selectedDate = els.reflectionDate.value || todayISO();
    els.reflectionStatus.hidden = true;
    try {
      state.reflection = await api.reflection(selectedDate);
      renderReflection();
    } catch (error) {
      els.reflectionStatus.textContent = error.message || '读取失败，原数据没有改变。';
      els.reflectionStatus.hidden = false;
    }
  });

  els.btnSaveReflection.addEventListener('click', async () => {
    const payload = {
      occurred_on: els.reflectionDate.value || todayISO(),
      highlight: els.reflectionHighlight.value.trim(),
      challenge: els.reflectionChallenge.value.trim(),
      gratitude: els.reflectionGratitude.value.trim(),
      note: els.reflectionNote.value.trim(),
    };
    if (![payload.highlight, payload.challenge, payload.gratitude, payload.note].some(Boolean)) {
      els.reflectionStatus.textContent = '亮点、困难、感谢或自由记录，至少填写一项。';
      els.reflectionStatus.hidden = false;
      els.reflectionHighlight.focus();
      return;
    }
    if (state.busy) return;
    state.busy = true;
    els.btnSaveReflection.disabled = true;
    els.reflectionStatus.hidden = true;
    try {
      const response = await api.saveReflection(payload);
      state.reflection = response.reflection_state;
      state.life = response.life;
      els.reflectionStatus.textContent = '已保存；同一天再次保存会更新这条回顾。';
      els.reflectionStatus.hidden = false;
      renderReflection(); renderLifeOverview();
    } catch (error) {
      els.reflectionStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.reflectionStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnSaveReflection.disabled = false;
    }
  });

  els.btnAddWorkout.addEventListener('click', async () => {
    const duration = Number(els.fitnessDuration.value);
    if (!(duration > 0)) { els.fitnessDuration.focus(); return; }
    if (state.busy) return;
    state.busy = true;
    els.btnAddWorkout.disabled = true;
    els.fitnessStatus.hidden = true;
    try {
      const response = await api.addWorkout({
        occurred_on: els.fitnessDate.value || todayISO(),
        activity: els.fitnessActivity.value,
        duration_minutes: duration,
        intensity: Number(els.fitnessIntensity.value),
        note: els.fitnessNote.value.trim(),
      });
      state.fitness = response.fitness;
      state.life = response.life;
      // 新记的这次训练要立刻能在「记一组」里选到，否则得刷新页面才行
      state.training = await api.trainingState();
      renderTraining();
      els.fitnessDuration.value = '';
      els.fitnessNote.value = '';
      els.fitnessStatus.textContent = '已保存，这次活动已经进入你的生活轨迹。';
      els.fitnessStatus.hidden = false;
      renderFitness(); renderLifeOverview();
    } catch (error) {
      els.fitnessStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.fitnessStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddWorkout.disabled = false;
    }
  });

  els.btnAddNutrition.addEventListener('click', async () => {
    const name = els.nutritionName.value.trim();
    if (!name) { els.nutritionName.focus(); return; }
    if (state.busy) return;
    const optionalNumber = input => input.value === '' ? null : Number(input.value);
    state.busy = true;
    els.btnAddNutrition.disabled = true;
    els.nutritionStatus.hidden = true;
    try {
      const response = await api.addNutrition({
        occurred_on: els.nutritionDate.value || todayISO(),
        meal_type: els.nutritionType.value,
        name,
        calories: optionalNumber(els.nutritionCaloriesInput),
        protein_g: optionalNumber(els.nutritionProteinInput),
        water_ml: optionalNumber(els.nutritionWaterInput),
        note: els.nutritionNote.value.trim(),
      });
      state.nutrition = response.nutrition;
      state.life = response.life;
      els.nutritionName.value = '';
      els.nutritionCaloriesInput.value = '';
      els.nutritionProteinInput.value = '';
      els.nutritionWaterInput.value = '';
      els.nutritionNote.value = '';
      els.nutritionStatus.textContent = '已保存，这条饮食记录已经进入你的生活轨迹。';
      els.nutritionStatus.hidden = false;
      renderNutrition(); renderLifeOverview();
    } catch (error) {
      els.nutritionStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.nutritionStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddNutrition.disabled = false;
    }
  });

  els.btnSaveRecovery.addEventListener('click', async () => {
    if (state.busy) return;
    const optionalNumber = input => input.value === '' ? null : Number(input.value);
    const payload = {
      occurred_on: els.recoveryDate.value || todayISO(),
      sleep_hours: optionalNumber(els.recoverySleepHours),
      sleep_quality: optionalNumber(els.recoverySleepQuality),
      energy: optionalNumber(els.recoveryEnergy),
      mood: optionalNumber(els.recoveryMood),
      note: els.recoveryNote.value.trim(),
    };
    if ([payload.sleep_hours, payload.sleep_quality, payload.energy, payload.mood].every(value => value == null) && !payload.note) {
      els.recoveryStatus.textContent = '睡眠、精力、心情或备注至少填写一项。';
      els.recoveryStatus.hidden = false;
      els.recoverySleepHours.focus();
      return;
    }
    state.busy = true;
    els.btnSaveRecovery.disabled = true;
    els.recoveryStatus.hidden = true;
    try {
      const response = await api.saveRecovery(payload);
      state.recovery = response.recovery;
      state.life = response.life;
      els.recoveryStatus.textContent = '已保存；同一天再次保存会更新这条记录。';
      els.recoveryStatus.hidden = false;
      renderRecovery(); renderLifeOverview();
    } catch (error) {
      els.recoveryStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.recoveryStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnSaveRecovery.disabled = false;
    }
  });

  els.btnAddStudy.addEventListener('click', async () => {
    const subject = els.studySubject.value.trim();
    const duration = Number(els.studyDuration.value);
    if (!subject) { els.studySubject.focus(); return; }
    if (!(duration > 0)) { els.studyDuration.focus(); return; }
    if (state.busy) return;
    state.busy = true;
    els.btnAddStudy.disabled = true;
    els.studyStatus.hidden = true;
    try {
      const response = await api.addStudy({
        occurred_on: els.studyDate.value || todayISO(),
        subject,
        duration_minutes: duration,
        focus: Number(els.studyFocus.value),
        note: els.studyNote.value.trim(),
      });
      state.study = response.study;
      state.life = response.life;
      els.studySubject.value = '';
      els.studyDuration.value = '';
      els.studyNote.value = '';
      els.studyStatus.textContent = '已保存，这段专注已经进入你的学习轨迹。';
      els.studyStatus.hidden = false;
      renderStudy(); renderLifeOverview();
    } catch (error) {
      els.studyStatus.textContent = error.message || '保存失败，原数据没有改变。';
      els.studyStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddStudy.disabled = false;
    }
  });

  els.btnAddTask.addEventListener('click', async () => {
    const title = els.taskTitle.value.trim();
    if (!title) { els.taskTitle.focus(); return; }
    if (state.busy) return;
    state.busy = true;
    els.btnAddTask.disabled = true;
    els.taskStatus.hidden = true;
    try {
      const response = await api.addTask({
        title,
        due_on: els.taskDue.value || state.life?.date || todayISO(),
        priority: els.taskPriority.value,
        category: els.taskCategory.value,
        note: '',
      });
      state.rhythm = response.rhythm;
      state.life = response.life;
      els.taskTitle.value = '';
      els.taskStatus.textContent = '待办已添加。';
      els.taskStatus.hidden = false;
      renderRhythm(); renderLifeOverview();
    } catch (error) {
      els.taskStatus.textContent = error.message || '添加失败，原数据没有改变。';
      els.taskStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddTask.disabled = false;
    }
  });

  els.btnAddHabit.addEventListener('click', async () => {
    const name = els.habitName.value.trim();
    if (!name) { els.habitName.focus(); return; }
    if (state.busy) return;
    state.busy = true;
    els.btnAddHabit.disabled = true;
    els.habitStatus.hidden = true;
    try {
      const response = await api.addHabit({ name, category: els.habitCategory.value });
      state.rhythm = response.rhythm;
      state.life = response.life;
      els.habitName.value = '';
      els.habitStatus.textContent = '每日习惯已添加。';
      els.habitStatus.hidden = false;
      renderRhythm(); renderLifeOverview();
    } catch (error) {
      els.habitStatus.textContent = error.message || '添加失败，原数据没有改变。';
      els.habitStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddHabit.disabled = false;
    }
  });

  els.taskTitle.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); els.btnAddTask.click(); }
  });
  els.habitName.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); els.btnAddHabit.click(); }
  });

  async function onDeleteWorkout(id) {
    if (state.busy || !window.confirm('删除这条健身记录？')) return;
    state.busy = true;
    try {
      const response = await api.delWorkout(id);
      state.fitness = response.fitness;
      state.training = await api.trainingState();
      renderTraining();
      state.life = response.life;
      renderFitness(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onDeleteNutrition(id) {
    if (state.busy || !window.confirm('删除这条饮食记录？')) return;
    state.busy = true;
    try {
      const response = await api.delNutrition(id);
      state.nutrition = response.nutrition;
      state.life = response.life;
      renderNutrition(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onDeleteRecovery(id) {
    if (state.busy || !window.confirm('删除这条恢复记录？')) return;
    state.busy = true;
    try {
      const response = await api.delRecovery(id);
      state.recovery = response.recovery;
      state.life = response.life;
      renderRecovery(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onDeleteStudy(id) {
    if (state.busy || !window.confirm('删除这条学习记录？')) return;
    state.busy = true;
    try {
      const response = await api.delStudy(id);
      state.study = response.study;
      state.life = response.life;
      renderStudy(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onToggleTask(id) {
    if (state.busy) return;
    state.busy = true;
    try {
      const response = await api.toggleTask(id);
      state.rhythm = response.rhythm;
      state.life = response.life;
      renderRhythm(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onDeleteTask(id) {
    if (state.busy || !window.confirm('删除这项待办？')) return;
    state.busy = true;
    try {
      const response = await api.delTask(id);
      state.rhythm = response.rhythm;
      state.life = response.life;
      renderRhythm(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onToggleHabit(id) {
    if (state.busy) return;
    state.busy = true;
    try {
      const response = await api.toggleHabit(id, { occurred_on: state.life?.date || todayISO() });
      state.rhythm = response.rhythm;
      state.life = response.life;
      renderRhythm(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onArchiveHabit(id) {
    if (state.busy || !window.confirm('归档这个习惯？历史打卡会保留。')) return;
    state.busy = true;
    try {
      const response = await api.archiveHabit(id);
      state.rhythm = response.rhythm;
      state.life = response.life;
      renderRhythm(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  async function onSetLifeGoalStatus(id, status) {
    if (state.busy) return;
    state.busy = true;
    try {
      const response = await api.setLifeGoalStatus(id, status);
      state.goals = response.goals;
      renderGoals();
    } finally { state.busy = false; }
  }

  async function onDeleteLifeGoal(id) {
    if (state.busy || !window.confirm('删除这个生活目标及其全部里程碑？')) return;
    state.busy = true;
    try {
      const response = await api.delLifeGoal(id);
      state.goals = response.goals;
      renderGoals();
    } finally { state.busy = false; }
  }

  async function onAddGoalMilestone(goalId) {
    const titleInput = els.goalsList.querySelector(`[data-goal-milestone-title="${goalId}"]`);
    const dateInput = els.goalsList.querySelector(`[data-goal-milestone-date="${goalId}"]`);
    const title = titleInput?.value.trim() || '';
    if (!title) { titleInput?.focus(); return; }
    if (state.busy) return;
    state.busy = true;
    try {
      const response = await api.addGoalMilestone(goalId, {
        title,
        target_date: dateInput?.value || null,
      });
      state.goals = response.goals;
      renderGoals();
    } finally { state.busy = false; }
  }

  async function onToggleGoalMilestone(id) {
    if (state.busy) return;
    state.busy = true;
    try {
      const response = await api.toggleGoalMilestone(id);
      state.goals = response.goals;
      renderGoals();
    } finally { state.busy = false; }
  }

  async function onDeleteGoalMilestone(id) {
    if (state.busy || !window.confirm('删除这个里程碑？')) return;
    state.busy = true;
    try {
      const response = await api.delGoalMilestone(id);
      state.goals = response.goals;
      renderGoals();
    } finally { state.busy = false; }
  }

  async function onDeleteReflection(id) {
    if (state.busy || !window.confirm('删除这条每日回顾？')) return;
    state.busy = true;
    try {
      const response = await api.delReflection(id);
      state.reflection = response.reflection;
      state.life = response.life;
      renderReflection(); renderLifeOverview();
    } finally { state.busy = false; }
  }

  function switchStageView(view) {
    state.currentView = view;
    els.viewTabs.forEach(tab => {
      const active = tab.dataset.view === view;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    els.stageViews.forEach(panel => { panel.hidden = panel.dataset.stageView !== view; });
    const titles = {
      today: ['今天', '— Daily Brief'],
      grid: ['人生方格', '— Life Runway'],
      dashboard: ['资金驾驶舱', '— Money Cockpit'],
      planning: ['规划中心', '— Plan Ahead'],
      review: ['月度日历', '— Monthly Review'],
      data: ['数据中心', '— Data & Reports'],
    };
    const title = titles[view] || titles.today;
    els.stageTitleCn.textContent = title[0];
    els.stageTitleEn.textContent = title[1];
    const isGrid = view === 'grid';
    els.stageChrome.classList.toggle('is-wide-tabs', !isGrid);
    els.stageLegend.hidden = !isGrid;
    if (isGrid) grid.resume(); else grid.pause();
    renderStats();
  }
  els.viewTabs.forEach(tab => tab.addEventListener('click', () => switchStageView(tab.dataset.view)));

  els.btnAddAccount.addEventListener('click', async () => {
    if (state.busy) return;
    const name = els.accountName.value.trim();
    if (!name) { els.accountName.focus(); return; }
    state.busy = true;
    els.btnAddAccount.disabled = true;
    els.accountError.hidden = true;
    try {
      const response = await api.addAccount({
        name,
        type: els.accountType.value,
        opening_balance: parseFloat(els.accountOpening.value) || 0,
      });
      state.accounts = response.accounts || [];
      state.stats = response.stats;
      els.accountName.value = '';
      els.accountOpening.value = '';
      grid.setData(state.stats);
      renderAll();
    } catch (error) {
      els.accountError.textContent = error.message || '账户创建失败';
      els.accountError.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddAccount.disabled = false;
    }
  });

  function applyFinanceResponse(response) {
    state.accounts = response.accounts || state.accounts;
    state.stats = response.stats || state.stats;
    state.monthly = response.monthly || state.monthly;
    state.transfers = response.transfers || state.transfers;
    state.planning = response.planning || state.planning;
    state.calendar = response.calendar || state.calendar;
    state.today = response.today || state.today;
    grid.setData(state.stats);
    renderAll();
  }

  function showOperationError(element, error) {
    element.textContent = error?.message || '操作失败，请检查后重试';
    element.hidden = false;
  }

  els.transferDate.value = todayISO();
  els.btnTransfer.addEventListener('click', async () => {
    if (state.busy) return;
    const fromAccountId = Number(els.transferFrom.value);
    const toAccountId = Number(els.transferTo.value);
    const amount = parseFloat(els.transferAmount.value);
    if (!fromAccountId || !toAccountId || fromAccountId === toAccountId) {
      showOperationError(els.transferError, new Error('请选择两个不同的账户'));
      return;
    }
    if (!(amount > 0)) { els.transferAmount.focus(); return; }
    state.busy = true;
    els.btnTransfer.disabled = true;
    els.transferError.hidden = true;
    try {
      const response = await api.transfer({
        from_account_id: fromAccountId,
        to_account_id: toAccountId,
        amount,
        occurred_on: els.transferDate.value || todayISO(),
        note: els.transferNote.value.trim(),
      });
      els.transferAmount.value = '';
      els.transferNote.value = '';
      applyFinanceResponse(response);
    } catch (error) {
      showOperationError(els.transferError, error);
    } finally {
      state.busy = false;
      els.btnTransfer.disabled = state.accounts.length < 2;
    }
  });

  els.reconcileAccount.addEventListener('change', renderAccountSelect);
  els.btnReconcile.addEventListener('click', async () => {
    if (state.busy) return;
    const accountId = Number(els.reconcileAccount.value);
    const actualBalance = parseFloat(els.reconcileBalance.value);
    const account = state.accounts.find(item => item.id === accountId);
    if (!account || !Number.isFinite(actualBalance)) {
      els.reconcileBalance.focus();
      return;
    }
    const delta = actualBalance - Number(account.balance);
    if (Math.abs(delta) < 0.005) {
      showOperationError(els.reconcileError, new Error('平台余额已经与实际余额一致'));
      return;
    }
    const confirmed = window.confirm(
      `将“${account.name}”从 ${fmtCNY(account.balance)} 校准为 ${fmtCNY(actualBalance)}？\n差额 ${fmtSignedCNY(delta)} 将作为校准记录保存，不计入收支。`
    );
    if (!confirmed) return;
    state.busy = true;
    els.btnReconcile.disabled = true;
    els.reconcileError.hidden = true;
    try {
      const response = await api.reconcile(accountId, {
        actual_balance: actualBalance,
        occurred_on: todayISO(),
        note: els.reconcileNote.value.trim() || '余额校准',
      });
      els.reconcileBalance.value = '';
      applyFinanceResponse(response);
    } catch (error) {
      showOperationError(els.reconcileError, error);
    } finally {
      state.busy = false;
      els.btnReconcile.disabled = state.accounts.length === 0;
    }
  });

  async function onDeleteTransfer(id) {
    if (state.busy) return;
    const transfer = state.transfers.find(item => item.id === id);
    if (!transfer) return;
    if (!window.confirm(`撤销 ${transfer.from_account_name} → ${transfer.to_account_name} 的 ${fmtCNY(transfer.amount)} 转账？`)) return;
    state.busy = true;
    try {
      applyFinanceResponse(await api.delTransfer(id));
    } catch (error) {
      showOperationError(els.transferError, error);
    } finally {
      state.busy = false;
    }
  }

  function applyPlanningResponse(response) {
    state.planning = {
      settings: response.settings || {},
      semester: response.semester || {},
      goals: response.goals || [],
      budget_status: response.budget_status || {},
      forecast: response.forecast || {},
    };
    renderPlanning();
    renderStats();
  }

  els.btnSavePlan.addEventListener('click', async () => {
    if (state.busy) return;
    state.busy = true;
    els.btnSavePlan.disabled = true;
    els.planSettingsStatus.hidden = true;
    try {
      const response = await api.savePlan({
        monthly_allowance_amount: parseFloat(els.planAllowanceAmount.value) || 0,
        allowance_day: parseInt(els.planAllowanceDay.value, 10) || 1,
        monthly_spending_budget: parseFloat(els.planBudget.value) || 0,
      });
      applyPlanningResponse(response);
      els.planSettingsStatus.textContent = '周期设置已保存；没有新增任何收入记录。';
      els.planSettingsStatus.classList.remove('plan-status--error');
      els.planSettingsStatus.hidden = false;
    } catch (error) {
      els.planSettingsStatus.textContent = error.message || '保存失败';
      els.planSettingsStatus.classList.add('plan-status--error');
      els.planSettingsStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnSavePlan.disabled = false;
    }
  });

  els.btnSaveSemester.addEventListener('click', async () => {
    if (state.busy) return;
    const startDate = els.semesterStart.value;
    const endDate = els.semesterEnd.value;
    if (!startDate) { els.semesterStart.focus(); return; }
    if (!endDate) { els.semesterEnd.focus(); return; }
    state.busy = true;
    els.btnSaveSemester.disabled = true;
    els.semesterStatus.hidden = true;
    try {
      const response = await api.saveSemester({
        start_date: startDate,
        end_date: endDate,
        total_budget: parseFloat(els.semesterBudget.value) || 0,
        mode: els.semesterMode.value || 'in_school',
      });
      applyPlanningResponse(response.planning || {});
      state.today = response.today || state.today;
      renderToday();
      renderStats();
      els.semesterStatus.textContent = '学期预算已保存；这只是预算，不会新增收入或支出。';
      els.semesterStatus.classList.remove('plan-status--error');
      els.semesterStatus.hidden = false;
    } catch (error) {
      els.semesterStatus.textContent = error.message || '学期预算保存失败';
      els.semesterStatus.classList.add('plan-status--error');
      els.semesterStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnSaveSemester.disabled = false;
    }
  });

  els.btnSaveBudgets.addEventListener('click', async () => {
    if (state.busy) return;
    const budgets = {};
    els.budgetList.querySelectorAll('[data-budget-category]').forEach(input => {
      budgets[input.dataset.budgetCategory] = parseFloat(input.value) || 0;
    });
    state.busy = true;
    els.btnSaveBudgets.disabled = true;
    els.budgetStatus.hidden = true;
    try {
      applyPlanningResponse(await api.saveBudgets({ budgets }));
      els.budgetStatus.textContent = '分类预算已保存。预算只提醒，不会改变账本。';
      els.budgetStatus.classList.remove('plan-status--error');
      els.budgetStatus.hidden = false;
    } catch (error) {
      els.budgetStatus.textContent = error.message || '预算保存失败';
      els.budgetStatus.classList.add('plan-status--error');
      els.budgetStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnSaveBudgets.disabled = false;
    }
  });

  els.btnDownloadTemplate.addEventListener('click', () => {
    const content = '\uFEFFdate,type,amount,category,source,note,account\r\n';
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = '财富自由指南灯-账单导入模板.csv';
    anchor.click();
    URL.revokeObjectURL(url);
  });

  els.btnAnalyzeImport.addEventListener('click', async () => {
    const file = els.importFile.files?.[0];
    els.importError.hidden = true;
    if (!file) { els.importFile.click(); return; }
    try {
      const text = await readStatementFile(file);
      state.importPreview = analyzeStatement(file.name, text);
      renderImportPreview();
    } catch (error) {
      state.importPreview = null;
      renderImportPreview();
      els.importError.textContent = error.message || 'CSV 无法解析';
      els.importError.hidden = false;
    }
  });

  els.btnAnalyzeStatement.addEventListener('click', async () => {
    const file = els.statementFile.files?.[0];
    els.statementError.hidden = true;
    if (!file) { els.statementFile.click(); return; }
    els.btnAnalyzeStatement.disabled = true;
    try {
      const text = await readStatementFile(file);
      state.statementPreview = await api.previewStatement({
        content: text,
        source: els.statementSource.value || null,
        filename: file.name,
      });
      renderStatementPreview();
    } catch (error) {
      state.statementPreview = null;
      renderStatementPreview();
      els.statementError.textContent = String(error.message || '账单无法解析').replace(/^\d+\s*/, '');
      els.statementError.hidden = false;
    } finally {
      els.btnAnalyzeStatement.disabled = false;
    }
  });

  els.btnCommitStatement.addEventListener('click', async () => {
    const preview = state.statementPreview;
    if (state.busy || !preview?.import_payload?.rows?.length) return;
    state.busy = true;
    els.btnCommitStatement.disabled = true;
    els.statementError.hidden = true;
    try {
      // 交给账本已有的安全导入：那里还有一层内容防重和整批撤销
      const response = await api.importTransactions(preview.import_payload);
      state.statementPreview = null;
      els.statementFile.value = '';
      await loadAndPaint();
      els.statementSummary.hidden = false;
      els.statementSummary.classList.remove('is-error');
      els.statementSummary.textContent =
        `已补录 ${response.imported_count || 0} 笔。重复的没有再记一遍，可以在上面的导入记录里整批撤销。`;
    } catch (error) {
      const duplicate = String(error.message || '').startsWith('409');
      els.statementError.textContent = duplicate
        ? '这批内容已经导入过，本次没有重复记账。'
        : String(error.message || '写入失败').replace(/^\d+\s*/, '');
      els.statementError.hidden = false;
      els.btnCommitStatement.disabled = false;
    } finally {
      state.busy = false;
    }
  });

  els.btnCommitImport.addEventListener('click', async () => {
    const preview = state.importPreview;
    if (state.busy || !preview || preview.errorCount > 0 || !preview.validRows.length) return;
    state.busy = true;
    els.btnCommitImport.disabled = true;
    els.importError.hidden = true;
    try {
      const response = await api.importTransactions({
        filename: preview.fileName,
        rows: preview.validRows,
      });
      const importedCount = response.imported_count || 0;
      state.importPreview = null;
      els.importFile.value = '';
      await loadAndPaint();
      els.importSummary.textContent = `已安全导入 ${importedCount} 笔账目。`;
      els.importSummary.classList.remove('is-error');
      els.importSummary.hidden = false;
    } catch (error) {
      const duplicate = String(error.message || '').startsWith('409');
      els.importError.textContent = duplicate ? '这份账单内容已经导入过，本次没有重复记账。' : (error.message || '导入失败');
      els.importError.hidden = false;
      els.btnCommitImport.disabled = false;
    } finally {
      state.busy = false;
    }
  });

  async function onDeleteImportBatch(id) {
    if (state.busy) return;
    const batch = state.importBatches.find(item => item.id === id);
    if (!batch) return;
    if (!window.confirm(`撤销“${batch.filename}”导入的 ${batch.remaining_rows} 笔账目？`)) return;
    state.busy = true;
    els.importError.hidden = true;
    try {
      const response = await api.delImportBatch(id);
      await loadAndPaint();
      els.importSummary.textContent = `已撤销整批导入，共删除 ${response.deleted_transactions} 笔账目。`;
      els.importSummary.classList.remove('is-error');
      els.importSummary.hidden = false;
    } catch (error) {
      els.importError.textContent = error.message || '撤销导入失败';
      els.importError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  els.btnAddGoal.addEventListener('click', async () => {
    if (state.busy) return;
    const name = els.goalName.value.trim();
    const targetAmount = parseFloat(els.goalTarget.value);
    const savedAmount = parseFloat(els.goalSaved.value) || 0;
    if (!name) { els.goalName.focus(); return; }
    if (!(targetAmount > 0)) { els.goalTarget.focus(); return; }
    state.busy = true;
    els.btnAddGoal.disabled = true;
    els.goalError.hidden = true;
    try {
      const response = await api.addGoal({
        name,
        target_amount: targetAmount,
        saved_amount: savedAmount,
        target_date: els.goalDate.value || null,
      });
      applyPlanningResponse(response);
      els.goalName.value = '';
      els.goalTarget.value = '';
      els.goalSaved.value = '';
      els.goalDate.value = '';
    } catch (error) {
      els.goalError.textContent = error.message || '目标创建失败';
      els.goalError.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddGoal.disabled = false;
    }
  });

  async function onUpdateGoal(id) {
    if (state.busy) return;
    const input = els.goalList.querySelector(`[data-goal-saved="${id}"]`);
    const savedAmount = parseFloat(input?.value);
    if (!Number.isFinite(savedAmount) || savedAmount < 0) { input?.focus(); return; }
    state.busy = true;
    try {
      applyPlanningResponse(await api.goalProgress(id, { saved_amount: savedAmount }));
    } catch (error) {
      els.goalError.textContent = error.message || '目标更新失败';
      els.goalError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  async function onDeleteGoal(id) {
    if (state.busy) return;
    const goal = state.planning.goals.find(item => item.id === id);
    if (!goal || !window.confirm(`删除储蓄目标“${goal.name}”？这不会影响账户余额。`)) return;
    state.busy = true;
    try {
      applyPlanningResponse(await api.delGoal(id));
    } catch (error) {
      els.goalError.textContent = error.message || '目标删除失败';
      els.goalError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  els.btnAddBill.addEventListener('click', async () => {
    if (state.busy) return;
    const name = els.billName.value.trim();
    const amount = parseFloat(els.billAmount.value);
    if (!name) { els.billName.focus(); return; }
    if (!(amount > 0)) { els.billAmount.focus(); return; }
    state.busy = true;
    els.btnAddBill.disabled = true;
    els.billError.hidden = true;
    try {
      const response = await api.addBill({
        name,
        amount,
        day_of_month: parseInt(els.billDay.value, 10) || 1,
        category: els.billCategory.value,
        account_id: Number(els.billAccount.value),
        note: els.billNote.value.trim(),
      });
      state.calendar = response.calendar;
      els.billName.value = '';
      els.billAmount.value = '';
      els.billNote.value = '';
      renderMonthlyReview();
      renderStats();
    } catch (error) {
      els.billError.textContent = error.message || '固定账单创建失败';
      els.billError.hidden = false;
    } finally {
      state.busy = false;
      els.btnAddBill.disabled = false;
    }
  });

  async function onPayBill(id) {
    if (state.busy) return;
    const bill = state.calendar.bills.find(item => item.id === id);
    if (!bill) return;
    if (!window.confirm(`将“${bill.name}”的 ${fmtCNY(bill.amount)} 记为本月真实支出？\n支付账户：${bill.account_name}`)) return;
    state.busy = true;
    try {
      await api.payBill(id, { month: state.calendar.month, paid_on: todayISO() });
      await loadAndPaint();
      switchStageView('review');
    } catch (error) {
      els.billError.textContent = String(error.message || '').startsWith('409') ? '这项固定账单本月已经支付过。' : (error.message || '支付记录失败');
      els.billError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  async function onUnpayBill(id) {
    if (state.busy) return;
    const bill = state.calendar.bills.find(item => item.id === id);
    if (!bill || !window.confirm(`撤销“${bill.name}”本月的支付记录？对应支出也会删除。`)) return;
    state.busy = true;
    try {
      await api.unpayBill(id, state.calendar.month);
      await loadAndPaint();
      switchStageView('review');
    } catch (error) {
      els.billError.textContent = error.message || '撤销支付失败';
      els.billError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  async function onDeleteBill(id) {
    if (state.busy) return;
    const bill = state.calendar.bills.find(item => item.id === id);
    if (!bill) return;
    const suffix = bill.is_paid ? ' 已生成的真实支出会保留。' : '';
    if (!window.confirm(`删除固定账单提醒“${bill.name}”？${suffix}`)) return;
    state.busy = true;
    try {
      const response = await api.delBill(id);
      state.calendar = response.calendar;
      renderMonthlyReview();
      renderStats();
    } catch (error) {
      els.billError.textContent = error.message || '删除提醒失败';
      els.billError.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  function downloadTextFile(filename, content, type) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  els.btnLoadAnnual.addEventListener('click', async () => {
    const year = parseInt(els.annualYear.value, 10);
    if (!(year >= 1900 && year <= 2200)) { els.annualYear.focus(); return; }
    state.busy = true;
    try {
      state.annualReport = await api.annualReport(year);
      renderDataCenter();
      renderStats();
    } finally { state.busy = false; }
  });

  els.btnExportAnnual.addEventListener('click', () => {
    const report = state.annualReport;
    if (!report) return;
    const lines = ['month,income,expense,family_support,independent_income,net_cashflow'];
    report.monthly.forEach(item => lines.push([
      item.month, item.income, item.expense, item.family_support,
      item.independent_income, item.net_cashflow,
    ].join(',')));
    downloadTextFile(`财富自由指南灯-${report.year}年度报告.csv`, `\uFEFF${lines.join('\r\n')}\r\n`, 'text/csv;charset=utf-8');
  });

  function currentSearchParams() {
    return {
      q: els.searchQuery.value.trim(),
      type: els.searchType.value,
      category: els.searchCategory.value,
      account_id: els.searchAccount.value,
      date_from: els.searchDateFrom.value,
      date_to: els.searchDateTo.value,
      limit: 500,
    };
  }

  els.btnSearch.addEventListener('click', async () => {
    if (state.busy) return;
    state.busy = true;
    try {
      state.searchResult = await api.searchTransactions(currentSearchParams());
      renderDataCenter();
    } catch (error) {
      els.searchSummary.textContent = error.message || '搜索失败';
    } finally { state.busy = false; }
  });
  els.searchQuery.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); els.btnSearch.click(); }
  });
  els.btnResetSearch.addEventListener('click', async () => {
    els.searchQuery.value = '';
    els.searchType.value = '';
    els.searchCategory.value = '';
    els.searchAccount.value = '';
    els.searchDateFrom.value = '';
    els.searchDateTo.value = '';
    state.searchResult = await api.searchTransactions({ limit: 200 });
    renderDataCenter();
  });

  els.btnExportBackup.addEventListener('click', async () => {
    if (state.busy) return;
    state.busy = true;
    els.backupStatus.hidden = true;
    try {
      const snapshot = await api.exportBackup();
      const stamp = String(snapshot.exported_at || todayISO()).replace(/[:.]/g, '-');
      downloadTextFile(`财富自由指南灯-完整备份-${stamp}.json`, JSON.stringify(snapshot, null, 2), 'application/json;charset=utf-8');
      els.backupStatus.textContent = `完整备份已导出：${snapshot.summary.transactions} 笔交易、${snapshot.summary.accounts} 个账户。`;
      els.backupStatus.classList.remove('plan-status--error');
      els.backupStatus.hidden = false;
    } catch (error) {
      els.backupStatus.textContent = error.message || '备份导出失败';
      els.backupStatus.classList.add('plan-status--error');
      els.backupStatus.hidden = false;
    } finally { state.busy = false; }
  });

  function syncRestoreButton() {
    els.btnRestoreBackup.disabled = !state.restoreSnapshot || els.restoreConfirm.value.trim() !== '恢复';
  }
  els.restoreConfirm.addEventListener('input', syncRestoreButton);
  els.restoreFile.addEventListener('change', async () => {
    state.restoreSnapshot = null;
    els.restorePreview.className = 'restore-preview';
    els.restoreConfirm.value = '';
    syncRestoreButton();
    const file = els.restoreFile.files?.[0];
    if (!file) { els.restorePreview.textContent = '尚未选择备份文件。'; return; }
    try {
      const snapshot = JSON.parse(await file.text());
      if (snapshot.format !== 'wealth-lighthouse-snapshot' || snapshot.version !== 1 || !snapshot.tables || !snapshot.summary) {
        throw new Error('不是受支持的财富自由指南灯备份');
      }
      state.restoreSnapshot = snapshot;
      els.restorePreview.classList.add('is-valid');
      els.restorePreview.textContent = `备份时间 ${String(snapshot.exported_at || '未知').replace('T', ' ')}；${snapshot.summary.accounts} 个账户、${snapshot.summary.transactions} 笔交易、${snapshot.summary.goals} 个目标、${snapshot.summary.bills} 个固定账单；余额 ${fmtCNY(snapshot.summary.current_balance)}。`;
    } catch (error) {
      els.restorePreview.classList.add('is-error');
      els.restorePreview.textContent = error.message || '备份文件无法解析';
    }
    syncRestoreButton();
  });

  els.btnRestoreBackup.addEventListener('click', async () => {
    if (state.busy || !state.restoreSnapshot || els.restoreConfirm.value.trim() !== '恢复') return;
    if (!window.confirm('恢复会覆盖当前全部数据。系统会先自动备份当前账本，确定继续吗？')) return;
    state.busy = true;
    els.btnRestoreBackup.disabled = true;
    els.backupStatus.hidden = true;
    try {
      const response = await api.restoreBackup({ snapshot: state.restoreSnapshot, confirmation: 'RESTORE' });
      state.restoreSnapshot = null;
      els.restoreFile.value = '';
      els.restoreConfirm.value = '';
      els.restorePreview.className = 'restore-preview';
      els.restorePreview.textContent = '恢复完成，当前页面已重新载入。';
      await loadAndPaint();
      switchStageView('data');
      els.backupStatus.textContent = `恢复成功。覆盖前自动备份：${response.automatic_backup}`;
      els.backupStatus.classList.remove('plan-status--error');
      els.backupStatus.hidden = false;
    } catch (error) {
      els.backupStatus.textContent = error.message || '恢复失败，当前账本未被覆盖';
      els.backupStatus.classList.add('plan-status--error');
      els.backupStatus.hidden = false;
      syncRestoreButton();
    } finally { state.busy = false; }
  });

  // ---------- 一句话记录 ----------
  // 一句话可能属于任何一个生活模块。账本的预览布局原样保留，
  // 只有判到别的模块时才切换成动态字段；判错了可以一键改判。
  const QUICK_MODULE_LABELS = {
    finance: '账本', fitness: '健身', nutrition: '饮食',
    recovery: '睡眠', study: '学习', rhythm: '待办',
  };

  const QUICK_FIELDS = {
    fitness: [
      { key: 'occurred_on', label: '日期', type: 'date' },
      { key: 'activity', label: '类型', type: 'select', options: [['strength', '力量'], ['cardio', '有氧'], ['sport', '球类 / 户外'], ['mobility', '拉伸 / 放松'], ['other', '其他']] },
      { key: 'duration_minutes', label: '时长（分钟）', type: 'number' },
      { key: 'intensity', label: '强度 1-10', type: 'number' },
      { key: 'note', label: '备注', type: 'text', wide: true },
    ],
    nutrition: [
      { key: 'occurred_on', label: '日期', type: 'date' },
      { key: 'meal_type', label: '餐次', type: 'select', options: [['breakfast', '早餐'], ['lunch', '午餐'], ['dinner', '晚餐'], ['snack', '加餐 / 饮水']] },
      { key: 'name', label: '内容', type: 'text' },
      { key: 'calories', label: '热量 kcal（可留空）', type: 'number' },
      { key: 'protein_g', label: '蛋白质 g（可留空）', type: 'number' },
      { key: 'water_ml', label: '饮水 ml（可留空）', type: 'number' },
    ],
    recovery: [
      { key: 'occurred_on', label: '日期', type: 'date' },
      { key: 'sleep_hours', label: '睡眠小时（可留空）', type: 'number' },
      { key: 'energy', label: '精力 1-5（可留空）', type: 'number' },
      { key: 'mood', label: '心情 1-5（可留空）', type: 'number' },
      { key: 'note', label: '备注', type: 'text', wide: true },
    ],
    study: [
      { key: 'occurred_on', label: '日期', type: 'date' },
      { key: 'subject', label: '科目', type: 'text' },
      { key: 'duration_minutes', label: '时长（分钟）', type: 'number' },
      { key: 'focus', label: '专注 1-5', type: 'number' },
      { key: 'note', label: '备注', type: 'text', wide: true },
    ],
    rhythm: [
      { key: 'title', label: '待办', type: 'text', wide: true },
      { key: 'due_on', label: '截止日', type: 'date' },
      { key: 'priority', label: '优先级', type: 'select', options: [['low', '低'], ['normal', '普通'], ['high', '高']] },
      { key: 'category', label: '归类', type: 'select', options: [['personal', '个人'], ['study', '学习'], ['health', '健康'], ['finance', '财务'], ['other', '其他']] },
    ],
  };

  function syncQuickPreviewType() {
    const isIncome = els.quickType.value === 'income';
    els.quickCategoryField.hidden = isIncome;
    els.quickSourceField.hidden = !isIncome;
  }

  function clearQuickPreview() {
    state.quickPreview = null;
    els.quickPreview.hidden = true;
    els.quickEntryStatus.hidden = true;
    els.quickWarnings.innerHTML = '';
    els.quickModules.hidden = true;
    els.quickModules.innerHTML = '';
    els.quickDynamic.hidden = true;
    els.quickDynamic.innerHTML = '';
    els.quickFinanceFields.hidden = false;
    els.btnQuickConfirm.textContent = '确认入账';
  }

  function renderQuickModules() {
    const preview = state.quickPreview;
    if (!preview) return;
    els.quickModules.hidden = false;
    els.quickModules.innerHTML = Object.keys(QUICK_MODULE_LABELS).map(key =>
      `<button type="button" class="quick-module${key === preview.module ? ' is-on' : ''}" data-quick-module="${key}">${QUICK_MODULE_LABELS[key]}</button>`
    ).join('');
    els.quickModules.querySelectorAll('[data-quick-module]').forEach(button => {
      button.addEventListener('click', () => switchQuickModule(button.dataset.quickModule));
    });
  }

  function renderQuickDynamic() {
    const preview = state.quickPreview;
    const fields = QUICK_FIELDS[preview.module] || [];
    const payload = preview.payload || {};
    els.quickDynamic.innerHTML = fields.map(field => {
      const value = payload[field.key] == null ? '' : String(payload[field.key]);
      const wide = field.wide ? ' class="is-wide"' : '';
      if (field.type === 'select') {
        const options = field.options
          .map(([key, label]) => `<option value="${key}"${key === value ? ' selected' : ''}>${label}</option>`)
          .join('');
        return `<label${wide}><span>${field.label}</span><select data-quick-field="${field.key}">${options}</select></label>`;
      }
      return `<label${wide}><span>${field.label}</span><input data-quick-field="${field.key}" type="${field.type}" value="${escapeHtml(value)}"></label>`;
    }).join('');
    els.quickDynamic.querySelectorAll('[data-quick-field]').forEach(input => {
      const sync = () => {
        const raw = input.value.trim();
        preview.payload[input.dataset.quickField] = raw === '' ? null : raw;
      };
      input.addEventListener('input', sync);
      input.addEventListener('change', sync);
    });
  }

  /** 换一个模块：让后端按新归属重新解析同一句话。
   *
   * 不在前端复制一份关键词逻辑——否则「午饭」在账本里认得出，
   * 改判到饮食后却变成了「加餐」。
   */
  async function switchQuickModule(moduleKey) {
    const preview = state.quickPreview;
    if (!preview || preview.module === moduleKey || state.busy) return;

    if (preview.payloads[moduleKey]) {
      applyQuickModule(moduleKey, preview.payloads[moduleKey]);
      return;
    }
    state.busy = true;
    els.quickEntryStatus.hidden = true;
    try {
      const parsed = await api.quickParse({ text: preview.input, module: moduleKey });
      const payload = parsed.matched ? Object.assign({}, parsed.preview) : {};
      preview.payloads[moduleKey] = payload;
      preview.confidences[moduleKey] = Number(parsed.confidence || 0);
      preview.moduleWarnings[moduleKey] = parsed.warnings || [];
      applyQuickModule(moduleKey, payload);
    } catch (error) {
      els.quickEntryStatus.textContent = String(error.message || '改判失败').replace(/^\d+\s*/, '');
      els.quickEntryStatus.hidden = false;
    } finally {
      state.busy = false;
    }
  }

  function applyQuickModule(moduleKey, payload) {
    const preview = state.quickPreview;
    preview.module = moduleKey;
    preview.payload = payload;
    els.quickConfidence.textContent =
      `${QUICK_MODULE_LABELS[moduleKey]} · 置信度 ${Math.round((preview.confidences[moduleKey] || 0) * 100)}%`;
    els.quickWarnings.innerHTML = (preview.moduleWarnings[moduleKey] || [])
      .map(item => `<div>• ${escapeHtml(item)}</div>`).join('');
    if (moduleKey === 'finance') {
      els.quickFinanceFields.hidden = false;
      els.quickDynamic.hidden = true;
      els.quickType.value = payload.type || 'expense';
      els.quickAmount.value = Number(payload.amount || 0) || '';
      fillAccountSelect(els.quickAccount, payload.account_id);
      els.quickCategory.value = payload.category || 'other';
      els.quickSource.value = payload.source || 'other';
      els.quickDate.value = payload.occurred_on || todayISO();
      els.quickNote.value = payload.note || preview.input;
      syncQuickPreviewType();
      els.btnQuickConfirm.textContent = '确认入账';
    } else {
      els.quickFinanceFields.hidden = true;
      els.quickDynamic.hidden = false;
      els.btnQuickConfirm.textContent = `确认记入${QUICK_MODULE_LABELS[moduleKey]}`;
      renderQuickDynamic();
    }
    renderQuickModules();
  }

  async function parseQuickEntry() {
    if (state.busy) return;
    const text = els.quickEntryInput.value.trim();
    if (!text) { els.quickEntryInput.focus(); return; }
    state.busy = true;
    els.btnQuickParse.disabled = true;
    els.quickEntryStatus.hidden = true;
    try {
      const parsed = await api.quickParse({ text });
      if (!parsed.matched) {
        clearQuickPreview();
        els.quickEntryStatus.textContent = parsed.reason || '认不出这句话属于哪个模块';
        els.quickEntryStatus.hidden = false;
        return;
      }
      state.quickPreview = {
        input: text,
        module: parsed.module,
        payload: Object.assign({}, parsed.preview),
        payloads: { [parsed.module]: Object.assign({}, parsed.preview) },
        confidences: { [parsed.module]: Number(parsed.confidence || 0) },
        moduleWarnings: { [parsed.module]: parsed.warnings || [] },
      };
      // 首次解析和改判走同一条渲染路径，避免两处逻辑日后走偏
      applyQuickModule(parsed.module, state.quickPreview.payload);
      els.quickPreview.hidden = false;
    } catch (error) {
      els.quickEntryStatus.textContent = String(error.message || '暂时无法解析这句话').replace(/^\d+\s*/, '');
      els.quickEntryStatus.hidden = false;
      els.quickPreview.hidden = true;
    } finally {
      state.busy = false;
      els.btnQuickParse.disabled = false;
    }
  }

  els.btnFocusStart.addEventListener('click', () => onStartFocus('focus'));
  els.btnBreakShort.addEventListener('click', () => onStartFocus('short_break', 5));
  els.btnBreakLong.addEventListener('click', () => onStartFocus('long_break', 15));
  els.btnFocusFinish.addEventListener('click', () => onFinishFocus(true));
  els.btnFocusDrop.addEventListener('click', () => onFinishFocus(false));
  els.focusRating.addEventListener('input', () => {
    els.focusRatingOutput.textContent = els.focusRating.value;
  });
  els.focusMinutes.addEventListener('input', () => {
    if (!state.focus?.running) renderFocus();
  });

  els.btnSaveBody.addEventListener('click', onSaveBody);
  els.btnAddSet.addEventListener('click', onAddSet);
  els.btnAddExercise.addEventListener('click', onAddExercise);
  els.btnAddInbox.addEventListener('click', onAddInbox);
  els.inboxInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); onAddInbox(); }
  });
  els.insightsDays.addEventListener('change', () => { reloadInsights(); });
  els.btnCleanupTags.addEventListener('click', async () => {
    if (state.busy) return;
    if (!window.confirm('清掉指向已删除记录的失效链接？来源记录不受影响。')) return;
    state.busy = true;
    try { await api.cleanupTags(); await reloadInsights(); } finally { state.busy = false; }
  });

  els.btnAnalyzeHealth.addEventListener('click', async () => {
    const file = els.healthFile.files?.[0];
    els.healthError.hidden = true;
    if (!file) { els.healthFile.click(); return; }
    els.btnAnalyzeHealth.disabled = true;
    try {
      const text = await readStatementFile(file);
      state.healthImportPreview = await api.previewHealth({
        content: text, kind: els.healthKind.value, filename: file.name,
      });
      renderHealthImport();
    } catch (error) {
      state.healthImportPreview = null;
      renderHealthImport();
      els.healthError.textContent = cleanError(error, '文件无法解析');
      els.healthError.hidden = false;
    } finally { els.btnAnalyzeHealth.disabled = false; }
  });

  els.btnCommitHealth.addEventListener('click', async () => {
    const preview = state.healthImportPreview;
    const rows = preview?.reconciliation?.new || [];
    if (state.busy || !rows.length) return;
    state.busy = true;
    els.btnCommitHealth.disabled = true;
    els.healthError.hidden = true;
    try {
      const response = await api.commitHealth({ kind: preview.kind, rows });
      state.healthImportPreview = null;
      els.healthFile.value = '';
      await loadAndPaint();
      els.healthSummary.hidden = false;
      els.healthSummary.textContent = response.failed.length
        ? `写入 ${response.imported} 条，${response.failed.length} 条没能写入。${response.note}`
        : `已写入 ${response.imported} 条。${response.note}`;
    } catch (error) {
      els.healthError.textContent = cleanError(error, '写入失败');
      els.healthError.hidden = false;
      els.btnCommitHealth.disabled = false;
    } finally { state.busy = false; }
  });

  els.btnQuickParse.addEventListener('click', parseQuickEntry);
  els.quickEntryInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); parseQuickEntry(); }
  });
  els.quickType.addEventListener('change', syncQuickPreviewType);
  els.btnQuickCancel.addEventListener('click', clearQuickPreview);
  els.btnQuickConfirm.addEventListener('click', async () => {
    if (state.busy) return;
    if (!state.settings) { showOverlay(); return; }
    const preview = state.quickPreview;
    if (!preview) return;

    // 账本走原来的入账路径，保留点亮方格的仪式动画
    if (preview.module === 'finance') {
      const amount = parseFloat(els.quickAmount.value);
      if (!(amount > 0)) { els.quickAmount.focus(); return; }
      state.busy = true;
      els.btnQuickConfirm.disabled = true;
      els.quickEntryStatus.hidden = true;
      try {
        const res = await api.addTx({
          type: els.quickType.value,
          source: els.quickType.value === 'income' ? els.quickSource.value : null,
          category: els.quickType.value === 'expense' ? els.quickCategory.value : null,
          account_id: Number(els.quickAccount.value),
          amount,
          note: els.quickNote.value.trim(),
          occurred_on: els.quickDate.value || todayISO(),
        });
        clearQuickPreview();
        els.quickEntryInput.value = '';
        await loadAndPaint();
        switchStageView('today');
        await playAnimation(res);
        grid.setData(state.stats);
        renderProgress();
      } catch (error) {
        els.quickEntryStatus.textContent = String(error.message || '入账失败，当前账本没有改变').replace(/^\d+\s*/, '');
        els.quickEntryStatus.hidden = false;
      } finally {
        state.busy = false;
        els.btnQuickConfirm.disabled = false;
      }
      return;
    }

    state.busy = true;
    els.btnQuickConfirm.disabled = true;
    els.quickEntryStatus.hidden = true;
    try {
      await api.quickCommit({ module: preview.module, payload: preview.payload });
      clearQuickPreview();
      els.quickEntryInput.value = '';
      await loadAndPaint();
    } catch (error) {
      els.quickEntryStatus.textContent = String(error.message || '写入失败，没有留下任何记录').replace(/^\d+\s*/, '');
      els.quickEntryStatus.hidden = false;
    } finally {
      state.busy = false;
      els.btnQuickConfirm.disabled = false;
    }
  });

  txDP.setValue(todayISO());
  els.txAmount.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); onSubmitTx(); }
  });
  els.btnSubmit.addEventListener('click', onSubmitTx);

  async function onSubmitTx() {
    if (state.busy) return;
    if (!state.settings) { showOverlay(); return; }
    const amount = parseFloat(els.txAmount.value);
    if (!(amount > 0)) { els.txAmount.focus(); return; }
    audio.ensure(); // 在 user gesture 同步路径里抓 audio context
    state.busy = true;
    els.btnSubmit.disabled = true;
    try {
      const res = await api.addTx({
        type: state.txType,
        source: state.txType === 'income' ? state.txSource : null,
        category: state.txType === 'expense' ? els.txCategory.value : null,
        account_id: Number(els.txAccount.value),
        amount,
        note: els.txNote.value.trim(),
        occurred_on: txDP.value || todayISO(),
      });
      state.transactions.unshift(res.transaction);
      state.transactions = state.transactions.slice(0, 50);
      state.stats = res.stats;
      state.accounts = res.accounts || state.accounts;
      state.monthly = res.monthly || state.monthly;
      state.planning = res.planning || state.planning;
      state.calendar = res.calendar || state.calendar;
      state.today = res.today || state.today;
      renderStats(); renderAccountSelect(); renderToday(); renderDashboard(); renderPlanning(); renderMonthlyReview(); renderTxList();
      await refreshDataCenterData();
      // 清表单
      els.txAmount.value = '';
      els.txNote.value = '';
      // 启动仪式
      await playAnimation(res);
      // 仪式结束后把 grid 状态对齐到 server（pastCells / totalCells 等字段）
      grid.setData(state.stats);
      renderProgress();
    } catch (e) {
      console.error(e);
    } finally {
      state.busy = false;
      els.btnSubmit.disabled = false;
    }
  }

  async function onDelete(id) {
    if (state.busy) return;
    audio.ensure();
    state.busy = true;
    try {
      const res = await api.delTx(id);
      state.transactions = state.transactions.filter(t => t.id !== id);
      state.stats = res.stats;
      state.accounts = res.accounts || state.accounts;
      state.monthly = res.monthly || state.monthly;
      state.planning = res.planning || state.planning;
      state.calendar = res.calendar || state.calendar;
      state.today = res.today || state.today;
      renderStats(); renderAccountSelect(); renderToday(); renderDashboard(); renderPlanning(); renderMonthlyReview(); renderTxList();
      await refreshDataCenterData();
      await playAnimation(res);
      grid.setData(state.stats);
      renderProgress();
    } catch (e) {
      console.error(e);
    } finally {
      state.busy = false;
    }
  }

  /** 根据后端返回 lit_before/lit_after/animation 编排 grid 动画 */
  async function playAnimation(res) {
    const before = res.lit_before ?? 0;
    const after  = res.lit_after  ?? 0;
    if (after > before) {
      await grid.lightUp(before, after);
    } else if (after < before) {
      await grid.extinguish(after, before);
    }
    // 当前资金覆盖全部未来（最后一格被点亮 · 首次跨越 future_cells）
    const future = state.stats.future_cells || 0;
    if (future > 0 && after >= future && before < future) {
      await celebrateFreedom();
    }
  }

  async function celebrateFreedom() {
    // 暂停 grid 渲染 · 让 banner CSS 独享主线程 & GPU
    grid.pause();
    els.freedomBanner.hidden = false;
    if (audio && audio.celebrateChord) audio.celebrateChord();
    await new Promise(r => setTimeout(r, 6500));
    els.freedomBanner.hidden = true;
    grid.resume();
  }

  // ============================================
  // 启动
  // ============================================
  grid.mount();
  stars.mount();
  loadAndPaint();

})();
