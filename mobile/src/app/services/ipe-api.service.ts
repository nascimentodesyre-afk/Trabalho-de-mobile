import {Injectable} from '@angular/core';import {HttpClient,HttpHeaders} from '@angular/common/http';import {Observable,of} from 'rxjs';import {catchError,map} from 'rxjs/operators';
export interface IpeUser{id_usuario:number;nome:string;e_mail:string;id_perfil:number;nome_perfil?:string;estatisticas?:{total:number;abertos:number;andamento:number;concluidos:number}}
export interface InventoryItem{id_patrimonio:number;nome:string;numero_patrimonio:string;valor_compra:number;valor_atual:number;data_aquisicao_formatada:string;nome_sala:string;nome_status:string}
export interface Ticket{id_chamado:number;data_abertura:string;descricao_problema:string;prioridade:string;nome_usuario:string;nome_patrimonio:string;nome_status:string}
export interface Movement{id_movimentacao:number;data_formatada:string;data_iso:string;sala_origem:string;bloco_origem:string|null;sala_destino:string;bloco_destino:string|null;total_itens:number}
export interface MovementSummary{total_movimentacoes:number;total_itens_movimentados:number;salas_envolvidas:number;ultima_movimentacao:string|null}
@Injectable({providedIn:'root'})export class IpeApiService{constructor(private http:HttpClient){}
login(email:string,senha:string,chave='',adminCheck=false):Observable<boolean>{const body=new URLSearchParams();body.set('email',email);body.set('senha',senha);if(chave)body.set('chave',chave);if(adminCheck)body.set('admin_check','on');return this.http.post('/login',body.toString(),{headers:new HttpHeaders({'Content-Type':'application/x-www-form-urlencoded'}),withCredentials:true,responseType:'text'}).pipe(map(()=>true),catchError(()=>of(false)))}
currentUser():Observable<IpeUser>{return this.http.get<IpeUser>('/api/dados_usuario',{withCredentials:true})}
getInventory():Observable<InventoryItem[]>{return this.http.get<InventoryItem[]>('/api/inventario/listar',{withCredentials:true})}
getTickets():Observable<Ticket[]>{return this.http.get<Ticket[]>('/api/chamados',{withCredentials:true})}
getMovements():Observable<Movement[]>{return this.http.get<Movement[]>('/api/movimentacoes',{withCredentials:true,params:{limite: '100'}})}
getMovementsSummary():Observable<MovementSummary>{return this.http.get<MovementSummary>('/api/movimentacoes/resumo',{withCredentials:true})}
logout():Observable<string>{return this.http.get('/logout',{responseType:'text',withCredentials:true})}
isAuthenticated():Observable<boolean>{return this.currentUser().pipe(map(()=>true),catchError(()=>of(false)))}}