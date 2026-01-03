import {Component} from '@angular/core';
import {CdkDragDrop, DragDropModule, moveItemInArray, transferArrayItem} from '@angular/cdk/drag-drop';
import {BahnRow, LaufOption} from './models';
import {CommonModule} from '@angular/common';
import {MatCardModule} from '@angular/material/card';
import {MatTableDataSource, MatTableModule} from '@angular/material/table';
import {FormsModule} from '@angular/forms';
import {MatInputModule} from '@angular/material/input';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatButtonModule} from '@angular/material/button';
import {MatSelectModule} from '@angular/material/select';

@Component({
  selector: 'app-stoppuhr',
  standalone: true,
  imports: [CommonModule,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSelectModule,
    MatTableModule,
    DragDropModule,
    ],
  templateUrl: './stoppuhr.component.html',
  styleUrls: ['./stoppuhr.component.scss'],
})
export class StoppuhrComponent {
  // Header-ish values typically come from app shell; kept here for feature demo
  baseUrl = '192.168.178.33:8082';
  startkartenPfad = '';
  statusText = 'Status: noch nicht geladen.';

  laufOptions: LaufOption[] = [
    { value: 'lauf1', label: 'Lauf 1' },
    { value: 'lauf2', label: 'Lauf 2' },
  ];
  selectedLauf: string | null = null;

  maxBahnenText = 'Max. Bahnen: –';
  letzteAktualisierungText = 'Letzte Aktualisierung: –';

  displayedColumns = ['bahn', 'name', 'startnr', 'disziplin', 'taster'];

  // Use MatTableDataSource for bahnen
  dataSource = new MatTableDataSource<BahnRow>([]);  // Initialized empty

  // Demo drag&drop
  tasterPool: string[] = ['Taster 1', 'Taster 2', 'Taster 3'];
  tasterAssigned: string[] = [];

  loadStartkarten() {
    // TODO: replace with API call
    this.statusText = 'Status: Startkarten geladen (Demo).';
    this.maxBahnenText = 'Max. Bahnen: 8 (Demo)';

    // Example data population (replace with real data from API)
    const demoBahnen: BahnRow[] = Array.from({ length: 8 }, (_, i) => ({
      bahn: i + 1,
      name: `Name ${i + 1}`,
      startnr: `Startnr ${i + 1}`,
      disziplin: `Disziplin ${i + 1}`,
      taster: ''
    }));

    this.dataSource.data = demoBahnen;  // Set data for MatTable
  }

  refreshTaster() {
    // TODO: replace with API call
    this.letzteAktualisierungText = `Letzte Aktualisierung: ${new Date().toLocaleString()}`;
  }

  dropTaster(event: CdkDragDrop<string[]>) {
    if (event.previousContainer === event.container) {
      moveItemInArray(event.container.data, event.previousIndex, event.currentIndex);
      return;
    }
    transferArrayItem(
      event.previousContainer.data,
      event.container.data,
      event.previousIndex,
      event.currentIndex
    );
  }
}
