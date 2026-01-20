import {Component, EventEmitter, Input, Output} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatChipsModule} from '@angular/material/chips';

export interface TasterVitals {
  batteryPercent?: number; // e.g. 90
  rssiDbm?: number;        // e.g. -50
}

@Component({
  selector: 'app-taster-card',
  standalone: true,
  imports: [CommonModule, MatChipsModule],
  templateUrl: './taster-card.component.html',
  styleUrls: ['./taster-card.component.scss'],
})
export class TasterCardComponent {
  /** Title (left) like "Taster A" */
  @Input({required: true}) title!: string;

  @Output() cardClick = new EventEmitter<void>();

  /** Optional subtitle line (e.g. "AABB:CC:DD:EE:00") */
  @Input() detail?: string;

  /** Optional vitals (battery / RSSI) */
  @Input() vitals?: TasterVitals;

  /** Optional badge text on the right (e.g. "BAHN 1 (aktiv)") */
  @Input() badgeText?: string;

  /** Optional: styles for badge; keep simple */
  @Input() badgeVariant: 'default' | 'active' | 'inactive' = 'default';

  get vitalsText(): string | null {
    if (!this.vitals) return null;

    const parts: string[] = [];
    if (this.vitals.batteryPercent != null) parts.push(`Akku: ${this.vitals.batteryPercent}%`);
    if (this.vitals.rssiDbm != null) parts.push(`RSSI: ${this.vitals.rssiDbm} dBm`);

    return parts.length ? parts.join(' | ') : null;
  }
}
