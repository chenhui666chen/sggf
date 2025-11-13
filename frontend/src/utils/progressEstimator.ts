/**
 * 进度估算器 - 基于时间预估的平滑进度条更新
 */

export interface StageDurations {
  concept: number
  structure: number
  content: number
  review: number
  iteration: number
}

export interface StageDurationRanges {
  concept: { min: number; max: number }
  structure: { min: number; max: number }
  content: { min: number; max: number }
  review: { min: number; max: number }
  iteration: { min: number; max: number }
}

export interface ProgressState {
  stage: string
  estimatedProgress: number  // 基于时间的预估进度 (0-100)
  realProgress: number        // 后端真实进度 (0-100)
  displayProgress: number     // 最终显示的进度 (0-100)
  startTime: number           // 阶段开始时间戳
  estimatedDuration: number   // 预估耗时（秒）
  elapsedTime: number         // 已经过时间（秒）
  remainingTime: number       // 预估剩余时间（秒）
  remainingTimeMin: number    // 🆕 预估剩余时间最小值（秒）
  remainingTimeMax: number    // 🆕 预估剩余时间最大值（秒）
}

export class ProgressEstimator {
  private stageDurations: StageDurations
  private stageDurationRanges: StageDurationRanges | null = null  // 🆕 置信区间
  private currentState: ProgressState | null = null
  private animationFrameId: number | null = null
  private onProgressUpdate: ((state: ProgressState) => void) | null = null

  constructor(stageDurations: StageDurations, stageDurationRanges?: StageDurationRanges) {
    this.stageDurations = stageDurations
    this.stageDurationRanges = stageDurationRanges || null
  }

  /**
   * 开始一个新阶段的进度估算
   */
  startStage(stage: string, onProgressUpdate: (state: ProgressState) => void) {
    // 停止之前的估算
    this.stop()

    const estimatedDuration = this.stageDurations[stage as keyof StageDurations] || 120

    // 🆕 获取置信区间
    const durationRange = this.stageDurationRanges?.[stage as keyof StageDurationRanges]
    const minDuration = durationRange?.min || estimatedDuration * 0.7
    const maxDuration = durationRange?.max || estimatedDuration * 1.3

    this.currentState = {
      stage,
      estimatedProgress: 0,
      realProgress: 0,
      displayProgress: 0,
      startTime: Date.now(),
      estimatedDuration,
      elapsedTime: 0,
      remainingTime: estimatedDuration,
      remainingTimeMin: minDuration,  // 🆕
      remainingTimeMax: maxDuration   // 🆕
    }

    this.onProgressUpdate = onProgressUpdate

    // 开始动画循环
    this.animate()
  }

  /**
   * 更新真实进度（来自后端）
   */
  updateRealProgress(progress: number) {
    if (!this.currentState) return

    this.currentState.realProgress = Math.max(0, Math.min(100, progress))
    this.updateDisplayProgress()
  }

  /**
   * 停止进度估算
   */
  stop() {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId)
      this.animationFrameId = null
    }
    this.currentState = null
    this.onProgressUpdate = null
  }

  /**
   * 完成当前阶段（立即跳到100%）
   */
  complete() {
    if (!this.currentState) return

    this.currentState.estimatedProgress = 100
    this.currentState.realProgress = 100
    this.currentState.displayProgress = 100
    this.currentState.remainingTime = 0
    this.currentState.remainingTimeMin = 0  // 🆕
    this.currentState.remainingTimeMax = 0  // 🆕

    if (this.onProgressUpdate) {
      this.onProgressUpdate({ ...this.currentState })
    }

    this.stop()
  }

  /**
   * 动画循环
   */
  private animate = () => {
    if (!this.currentState) return

    const now = Date.now()
    const elapsedMs = now - this.currentState.startTime
    const elapsedSeconds = elapsedMs / 1000

    this.currentState.elapsedTime = elapsedSeconds

    // 计算基于时间的预估进度
    const timeProgress = (elapsedSeconds / this.currentState.estimatedDuration) * 100

    // 如果超过预估时间，进度减缓（渐近100%但不到达）
    if (timeProgress >= 100) {
      // 使用对数函数减缓进度增长
      const overtime = elapsedSeconds - this.currentState.estimatedDuration
      const slowdownFactor = Math.log(overtime + 1) / Math.log(10)  // 对数减缓
      this.currentState.estimatedProgress = Math.min(95, 90 + slowdownFactor * 5)
    } else {
      this.currentState.estimatedProgress = timeProgress
    }

    // 更新剩余时间（包括置信区间）
    if (this.currentState.estimatedProgress < 100) {
      const remainingProgress = 100 - this.currentState.displayProgress

      // 🆕 获取置信区间
      const durationRange = this.stageDurationRanges?.[this.currentState.stage as keyof StageDurationRanges]
      const minDuration = durationRange?.min || this.currentState.estimatedDuration * 0.7
      const maxDuration = durationRange?.max || this.currentState.estimatedDuration * 1.3

      // 计算剩余时间的置信区间
      this.currentState.remainingTimeMin = (remainingProgress / 100) * minDuration
      this.currentState.remainingTimeMax = (remainingProgress / 100) * maxDuration

      // 平均剩余时间
      this.currentState.remainingTime = (this.currentState.remainingTimeMin + this.currentState.remainingTimeMax) / 2
    } else {
      this.currentState.remainingTime = 0
      this.currentState.remainingTimeMin = 0
      this.currentState.remainingTimeMax = 0
    }

    // 更新显示进度
    this.updateDisplayProgress()

    // 通知更新
    if (this.onProgressUpdate) {
      this.onProgressUpdate({ ...this.currentState })
    }

    // 继续动画
    this.animationFrameId = requestAnimationFrame(this.animate)
  }

  /**
   * 更新显示进度（融合预估进度和真实进度）
   */
  private updateDisplayProgress() {
    if (!this.currentState) return

    const { estimatedProgress, realProgress } = this.currentState

    // 融合策略：
    // 1. 如果有真实进度，优先使用真实进度
    // 2. 如果真实进度 > 预估进度，使用真实进度
    // 3. 如果真实进度 < 预估进度，使用加权平均（真实进度权重更高）
    // 4. 如果没有真实进度，使用预估进度

    if (realProgress > 0) {
      if (realProgress >= estimatedProgress) {
        // 真实进度更快，直接使用
        this.currentState.displayProgress = realProgress
      } else {
        // 真实进度较慢，使用加权平均（真实进度权重70%，预估进度权重30%）
        this.currentState.displayProgress = realProgress * 0.7 + estimatedProgress * 0.3
      }
    } else {
      // 没有真实进度，使用预估进度
      this.currentState.displayProgress = estimatedProgress
    }

    // 确保进度不倒退
    if (this.currentState.displayProgress < (this.currentState as any).lastDisplayProgress) {
      this.currentState.displayProgress = (this.currentState as any).lastDisplayProgress
    }

    (this.currentState as any).lastDisplayProgress = this.currentState.displayProgress
  }
}

