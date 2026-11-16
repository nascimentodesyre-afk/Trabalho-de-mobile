import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LoginPage } from './pages/login/login.page';
import { HomePage } from './pages/home/home.page';
import { InventoryPage } from './pages/inventory/inventory.page';
import { PatrimonioFormPage } from './pages/patrimonio-form/patrimonio-form.page';
import { TicketsPage } from './pages/tickets/tickets.page';
import { MovementsPage } from './pages/movements/movements.page';
import { authGuard } from './services/auth.guard';

const routes: Routes = [
  { path: 'login', component: LoginPage },
  { path: 'home', component: HomePage, canActivate: [authGuard] },
  { path: 'inventario', component: InventoryPage, canActivate: [authGuard] },
  { path: 'patrimonio/novo', component: PatrimonioFormPage, canActivate: [authGuard] },
  { path: 'chamados', component: TicketsPage, canActivate: [authGuard] },
  { path: 'movimentacoes', component: MovementsPage, canActivate: [authGuard] },
  { path: '', redirectTo: 'home', pathMatch: 'full' },
  { path: '**', redirectTo: 'home' }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule {}
