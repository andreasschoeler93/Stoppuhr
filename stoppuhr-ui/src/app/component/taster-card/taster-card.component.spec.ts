import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TasterCardComponent } from './taster-card.component';

describe('TasterCardComponent', () => {
  let component: TasterCardComponent;
  let fixture: ComponentFixture<TasterCardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TasterCardComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TasterCardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
