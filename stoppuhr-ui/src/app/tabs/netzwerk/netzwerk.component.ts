import {Component, inject, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';

import {MatCardModule} from '@angular/material/card';
import {MatButtonModule} from '@angular/material/button';
import {MatDividerModule} from '@angular/material/divider';

import {StatusService} from '../../services/status.service';

@Component({
  selector: 'app-netzwerk',
  standalone: true,
  imports: [CommonModule, MatCardModule, MatButtonModule, MatDividerModule],
  templateUrl: './netzwerk.component.html',
  styleUrls: ['./netzwerk.component.scss'],
})
export class NetzwerkComponent implements OnInit {
  private readonly refreshTick = signal(0);
  readonly letzteAktualisierung = signal<string>('–');

  private statusService = inject(StatusService);

  readonly netzwerk = this.statusService.networkStatusResource


  ngOnInit() {
    this.refresh();
  }

  refresh() {
    this.refreshTick.update(v => v + 1);
    this.letzteAktualisierung.set(new Date().toLocaleTimeString());
  }


}
