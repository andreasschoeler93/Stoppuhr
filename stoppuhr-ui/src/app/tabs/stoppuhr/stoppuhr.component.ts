import {Component, computed, inject} from '@angular/core';
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
import {StatusService} from '../../services/status.service';
import {JAuswertungService} from '../../services/jauswertung.service';

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

  private statusService = inject(StatusService);
  protected jauswertungService = inject(JAuswertungService);

  fullUrl = computed(() => {
    const s = this.statusService.settingsResource.value();
    if (!s || !s.startcards_base_url) return 'URL nicht konfiguriert';
    return s.startcards_base_url + (s.startcards_suffix || '');
  });
    statusText = computed(() => {
    const resource = this.jauswertungService.startkartenResource;

    if (resource.isLoading()) return 'Lade Startkarten...';
    if (resource.error()) {
      // You can check the error object here if needed
      return 'Fehler: Konnte Startkarten nicht laden.';
    }
    if (resource.value()) {
      return `Erfolgreich geladen (${new Date().toLocaleTimeString()})`;
    }
    return 'Status: bereit.';
  });

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
    this.maxBahnenText = 'Max. Bahnen: 8 (Demo)';

    // // Example data population (replace with real data from API)
    // const demoBahnen: BahnRow[] = Array.from({ length: 8 }, (_, i) => ({
    //   bahn: i + 1,
    //   name: `Name ${i + 1}`,
    //   startnr: `Startnr ${i + 1}`,
    //   disziplin: `Disziplin ${i + 1}`,
    //   taster: ''
    // }));
    this.jauswertungService.reload();

    // this.dataSource.data = demoBahnen;  // Set data for MatTable

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
