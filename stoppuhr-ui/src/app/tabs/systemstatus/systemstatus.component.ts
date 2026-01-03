import {Component} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatCardModule} from '@angular/material/card';

@Component({
  selector: 'app-systemstatus',
  standalone: true,
  imports: [CommonModule, MatCardModule],
  templateUrl: './systemstatus.component.html',
  styleUrls: ['./systemstatus.component.scss'],
})
export class SystemstatusComponent {
  // stub
  status = [
    { key: 'Backend', value: 'Unbekannt' },
    { key: 'Datenbank', value: 'Unbekannt' },
    { key: 'Taster-Gateway', value: 'Unbekannt' },
  ];
}
