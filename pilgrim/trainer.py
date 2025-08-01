import torch
import os
import time
import pandas as pd
import math
from .model import Pilgrim

class Trainer:
    def __init__(self, 
                 net, num_epochs, device, 
                 batch_size=10000, lr=0.001, name="", K_min=1, K_max=55, 
                 all_moves=None, inverse_moves=None, V0=None, 
                 optimizer='Adam', # Adam or AdamSF
                 α=0.001, # Not supported for this branch
                ):
        self.net = net.to(device)
        self.α = α
        self.lr = lr
        self.device = device
        self.num_epochs = num_epochs
        self.batch_size = batch_size
        self.criterion = torch.nn.MSELoss()
        self.optimizer = torch.optim.Adam(self.net.parameters(), lr=lr)
        self.epoch = 0
        self.id = int(time.time())
        self.log_dir = "logs"
        self.weights_dir = "weights"
        self.name = name
        self.K_min = K_min
        self.K_max = K_max
        self.walkers_num = 1_000_000 // self.K_max
        self.all_moves = all_moves
        self.n_gens = all_moves.size(0)
        self.state_size = all_moves.size(1)
        self.inverse_moves = inverse_moves
        self.V0 = V0
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.weights_dir, exist_ok=True)

    def do_random_step(self, states, last_moves):
        """Perform a random step while avoiding inverse moves."""
        possible_moves = torch.ones((states.size(0), self.n_gens), dtype=torch.bool, device=self.device)
        possible_moves[torch.arange(states.size(0)), self.inverse_moves[last_moves]] = False
        next_moves = torch.multinomial(possible_moves.float(), 1).squeeze()
        new_states = torch.gather(states, 1, self.all_moves[next_moves])
        return new_states, next_moves

    def generate_random_walks(self, k=1000, K_min=1, K_max=30):
        """Random walks from K_min to K_max steps with k walkers."""
        total = k * (K_max - K_min + 1)
        Y = torch.arange(K_min, K_max + 1, device=self.device).repeat_interleave(k)
        states = self.V0.repeat(total, 1)
        last_moves = torch.full((total,), -1, dtype=torch.int64, device=self.device)
        for t in range(K_max):
            cutoff = 0 if t < K_min else k * (t - K_min + 1)
            if cutoff < total:
                states[cutoff:], last_moves[cutoff:] = self.do_random_step(states[cutoff:], last_moves[cutoff:])
            else:
                break
        perm = torch.randperm(total, device=self.device)
        return states[perm], Y[perm]
        
    def _train_epoch(self, X, Y):
        self.net.train()
        avg_loss = 0.0
        total_batches = X.size(0) // self.batch_size
        
        for i in range(0, X.size(0), self.batch_size):
            data = X[i:i + self.batch_size]
            target = Y[i:i + self.batch_size]
            output = self.net(data)

            
            loss = self.criterion(output, target)
            print(f'batch: {i}; output: {output}; target: {target}; loss: {loss};;;')
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
            print(f' :  ;  :  ;  :  ;  : ; avg_loss={avg_loss}')
            avg_loss += loss.item()

        return avg_loss / total_batches if total_batches > 0 else avg_loss

    def run(self):
        for epoch in range(self.num_epochs):
            self.epoch += 1

            # Data generation
            data_gen_start = time.time()
            X, Y = self.generate_random_walks(k=self.walkers_num, K_min=self.K_min, K_max=self.K_max)
            data_gen_time = time.time() - data_gen_start
            print(f"X: {X}; Y: {Y}")

            
            # Training step
            epoch_start = time.time()
            train_loss = self._train_epoch(X, Y.float())
            epoch_time = time.time() - epoch_start

            # Log training data
            log_file = f"{self.log_dir}/train_{self.name}_{self.id}.csv"
            log_data = pd.DataFrame([{
                'epoch': self.epoch, 
                'train_loss': train_loss, 
                'vertices_seen': X.size(0),
                'data_gen_time': data_gen_time,
                'train_epoch_time': epoch_time
            }])
            log_data.to_csv(log_file, mode='a', header=not os.path.exists(log_file), index=False)

            # Save weights on powers of two
            if (self.epoch & (self.epoch - 1)) == 0:
                weights_file = f"{self.weights_dir}/{self.name}_{self.id}_e{self.epoch:05d}.pth"
                torch.save(self.net.state_dict(), weights_file)

                # Print saving information with timestamp and train loss
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                print(f"[{timestamp}] Saved weights at epoch {self.epoch:5d}. Train Loss: {train_loss:.2f}")

        # Save final weights
        if (self.epoch & (self.epoch - 1)) != 0:
            final_weights_file = f"{self.weights_dir}/{self.name}_{self.id}_e{self.epoch:05d}.pth"
            torch.save(self.net.state_dict(), final_weights_file)

        # Print final saving information
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        print(f"[{timestamp}] Finished. Saved final weights at epoch {self.epoch}. Train Loss: {train_loss:.2f}.")
