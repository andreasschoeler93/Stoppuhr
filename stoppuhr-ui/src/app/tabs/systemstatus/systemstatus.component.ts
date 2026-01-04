import {Component, inject} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatCardModule} from '@angular/material/card';
import {MatButtonModule} from '@angular/material/button';
import {MatDividerModule} from '@angular/material/divider';
import {SystemStatusService} from '../../services/system-status.service';

@Component({
  selector: 'app-systemstatus',
  standalone: true,
  imports: [CommonModule, MatCardModule, MatButtonModule, MatDividerModule],
  templateUrl: './systemstatus.component.html',
  styleUrl: './systemstatus.component.scss'
})
export class SystemstatusComponent {
  private statusService = inject(SystemStatusService);

  // Use the resource from the service
  // In the template, we access it via systemStatus.value()
  systemStatus = this.statusService.systemResource;

  get letzteAktualisierung() {
    return new Date().toLocaleString();
  }

  refresh() {
    this.systemStatus.reload();
  }

  dienstLabel(state: string | undefined): string {
    if (!state) return 'Unbekannt';
    return state === 'active' ? 'Aktiv' : 'Inaktiv';
  }
}
